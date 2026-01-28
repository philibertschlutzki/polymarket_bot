#!/usr/bin/env python3
"""
Polymarket AI Value Bet Bot

Ein Bot zur Identifizierung von Value Bets auf Polymarket durch Kombination von:
- Marktdaten aus der Polymarket Gamma API
- KI-gestützte Wahrscheinlichkeitsschätzung via Google Gemini mit Search Grounding
- Kelly-Kriterium zur Positionsgrößenbestimmung (max. 50% des Kapitals)
"""

import os
import sys
from typing import Optional, List
from datetime import datetime

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from py_clob_client.client import ClobClient


# ============================================================================
# KONFIGURATION
# ============================================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "1000"))

if not GEMINI_API_KEY:
    print("❌ Fehler: GEMINI_API_KEY nicht in .env gefunden!")
    sys.exit(1)

POLYMARKET_API_URL = "https://gamma-api.polymarket.com/events"
MIN_VOLUME = 10000  # Mindestvolumen in USD für Markt-Selektion
KELLY_FRACTION = 0.25  # Fractional Kelly (25% der Full Kelly)
MAX_CAPITAL_FRACTION = 0.5  # Maximum 50% des Kapitals pro Wette


# ============================================================================
# DATENMODELLE
# ============================================================================

class MarketData(BaseModel):
    """Datenmodell für einen Polymarket-Markt."""
    
    question: str = Field(..., description="Die Marktfrage")
    description: str = Field(default="", description="Detaillierte Marktbeschreibung")
    market_slug: str = Field(..., description="Eindeutige ID des Marktes")
    yes_price: float = Field(..., description="Aktueller Preis für 'Yes' (0.0-1.0)")
    volume: float = Field(..., description="Handelsvolumen in USD")
    end_date: Optional[str] = Field(None, description="Enddatum des Marktes")


class AIAnalysis(BaseModel):
    """Datenmodell für die KI-Analyse."""
    
    estimated_probability: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Von der KI geschätzte Wahrscheinlichkeit (0.0-1.0)"
    )
    confidence_score: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Confidence-Score der KI (0.0-1.0)"
    )
    reasoning: str = Field(..., description="Begründung der KI")


class TradingRecommendation(BaseModel):
    """Datenmodell für eine Handelsempfehlung."""
    
    action: str = Field(..., description="Empfehlung: YES, NO oder PASS")
    stake_usdc: float = Field(..., description="Empfohlener Einsatz in USDC")
    kelly_fraction: float = Field(..., description="Kelly-Fraction des Kapitals")
    expected_value: float = Field(..., description="Erwarteter Gewinn")
    market_question: str = Field(..., description="Die Marktfrage")


# ============================================================================
# POLYMARKET API INTEGRATION
# ============================================================================

def fetch_active_markets(limit: int = 20) -> List[MarketData]:
    """
    Holt aktive Märkte von der Polymarket CLOB API.
    Falls die API nicht erreichbar ist, werden Mock-Daten zurückgegeben.
    
    Args:
        limit: Maximale Anzahl der zurückzugebenden Märkte
        
    Returns:
        Liste von MarketData-Objekten
    """
    try:
        print(f"📡 Verbinde mit Polymarket API...")
        
        # Initialize the CLOB client
        client = ClobClient(host="https://clob.polymarket.com")
        
        # Fetch markets
        response = client.get_markets()
        
        markets = []
        
        if not response or 'data' not in response:
            print(f"⚠️  Keine Marktdaten erhalten")
            return markets
        
        market_data_list = response['data']
        
        for market in market_data_list:
            # Skip if not active
            if not market.get('active', False):
                continue
            
            # Filter by volume
            volume = float(market.get('volume', 0))
            if volume < MIN_VOLUME:
                continue
            
            # Get the question/description
            question = market.get('question', '')
            description = market.get('description', '')
            
            # Get outcome prices - typically [Yes, No]
            outcome_prices = market.get('outcome_prices', ['0.5', '0.5'])
            yes_price = float(outcome_prices[0]) if outcome_prices else 0.5
            
            markets.append(MarketData(
                question=question,
                description=description,
                market_slug=market.get('condition_id', ''),
                yes_price=yes_price,
                volume=volume,
                end_date=market.get('end_date_iso')
            ))
            
            # Stop when we have enough markets
            if len(markets) >= limit:
                break
        
        print(f"✅ {len(markets)} Märkte mit Volumen >${MIN_VOLUME:,.0f} gefunden\n")
        return markets
        
    except Exception as e:
        error_msg = str(e)
        print(f"⚠️  Fehler beim Abrufen der Märkte: {error_msg}")
        
        # Check if it's a network/DNS error
        if "No address associated with hostname" in error_msg or "ConnectError" in error_msg or "PolyApiException" in error_msg:
            print(f"ℹ️  Die Polymarket API ist in dieser Umgebung nicht erreichbar.")
            print(f"ℹ️  Dies kann aufgrund von Netzwerkbeschränkungen auftreten.")
            print(f"ℹ️  Bitte stellen Sie sicher, dass:")
            print(f"   1. Sie eine Internetverbindung haben")
            print(f"   2. Die Domain 'clob.polymarket.com' erreichbar ist")
            print(f"   3. Keine Firewall die Verbindung blockiert")
            print(f"\n💡 Tipp: Führen Sie 'curl https://clob.polymarket.com/markets' aus, um die Erreichbarkeit zu testen.\n")
        else:
            # For other errors, print traceback
            import traceback
            traceback.print_exc()
        
        return []


# ============================================================================
# GOOGLE GEMINI AI INTEGRATION
# ============================================================================

def analyze_market_with_ai(market: MarketData) -> Optional[AIAnalysis]:
    """
    Analysiert einen Markt mit Google Gemini und Google Search Grounding.
    
    Args:
        market: Das zu analysierende MarketData-Objekt
        
    Returns:
        AIAnalysis-Objekt oder None bei Fehler
    """
    try:
        # Konfiguriere Gemini Client
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Erstelle den Prompt
        prompt = f"""
Analysiere folgende Wettfrage von Polymarket und schätze die Wahrscheinlichkeit ein:

FRAGE: {market.question}

BESCHREIBUNG: {market.description}

AKTUELLER MARKTPREIS (Yes): {market.yes_price:.2%}

Nutze aktuelle Fakten aus dem Internet (Google Search), um eine fundierte Einschätzung zu geben.

Antworte im folgenden Format:
WAHRSCHEINLICHKEIT: [Zahl zwischen 0.0 und 1.0]
CONFIDENCE: [Dein Confidence-Level zwischen 0.0 und 1.0]
BEGRÜNDUNG: [Deine ausführliche Begründung mit Quellen]

Wichtig: 
- Sei objektiv und faktenbezogen
- Berücksichtige aktuelle Entwicklungen
- Gib einen realistischen Confidence-Score an
"""
        
        print(f"🤖 Analysiere mit Gemini: {market.question[:60]}...")
        
        # Nutze Gemini 2.0 Flash mit Google Search
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        
        text = response.text
        
        # Parse die Antwort
        lines = text.strip().split('\n')
        probability = None
        confidence = None
        reasoning_parts = []
        
        in_reasoning = False
        for line in lines:
            line = line.strip()
            if line.startswith('WAHRSCHEINLICHKEIT:'):
                prob_str = line.split(':', 1)[1].strip()
                try:
                    probability = float(prob_str)
                except ValueError:
                    # Versuche Prozent-Format zu parsen
                    prob_str = prob_str.replace('%', '').strip()
                    probability = float(prob_str) / 100 if float(prob_str) > 1 else float(prob_str)
            elif line.startswith('CONFIDENCE:'):
                conf_str = line.split(':', 1)[1].strip()
                try:
                    confidence = float(conf_str)
                except ValueError:
                    conf_str = conf_str.replace('%', '').strip()
                    confidence = float(conf_str) / 100 if float(conf_str) > 1 else float(conf_str)
            elif line.startswith('BEGRÜNDUNG:'):
                reasoning_parts.append(line.split(':', 1)[1].strip())
                in_reasoning = True
            elif in_reasoning and line:
                reasoning_parts.append(line)
        
        reasoning = ' '.join(reasoning_parts) if reasoning_parts else text
        
        # Validierung
        if probability is None or confidence is None:
            print("⚠️  Konnte Wahrscheinlichkeit nicht parsen, nutze Standardwerte")
            # Fallback: Versuche Zahlen aus dem Text zu extrahieren
            import re
            numbers = re.findall(r'0\.\d+', text)
            if len(numbers) >= 2:
                probability = float(numbers[0])
                confidence = float(numbers[1])
            else:
                return None
        
        # Stelle sicher, dass Werte im gültigen Bereich sind
        probability = max(0.0, min(1.0, probability))
        confidence = max(0.0, min(1.0, confidence))
        
        return AIAnalysis(
            estimated_probability=probability,
            confidence_score=confidence,
            reasoning=reasoning
        )
        
    except Exception as e:
        print(f"❌ Fehler bei KI-Analyse: {e}")
        return None


# ============================================================================
# KELLY CRITERION & RISK MANAGEMENT
# ============================================================================

def calculate_kelly_stake(
    ai_probability: float,
    market_price: float,
    confidence: float,
    capital: float
) -> TradingRecommendation:
    """
    Berechnet die optimale Einsatzhöhe nach dem Kelly-Kriterium.
    
    Args:
        ai_probability: Von der KI geschätzte Wahrscheinlichkeit (0.0-1.0)
        market_price: Aktueller Marktpreis (0.0-1.0)
        confidence: Confidence-Score der KI (0.0-1.0)
        capital: Verfügbares Gesamtkapital in USDC
        
    Returns:
        TradingRecommendation-Objekt
    """
    # Berechne Netto-Odds: b = (1 / Marktpreis) - 1
    if market_price <= 0 or market_price >= 1:
        return TradingRecommendation(
            action="PASS",
            stake_usdc=0.0,
            kelly_fraction=0.0,
            expected_value=0.0,
            market_question=""
        )
    
    net_odds = (1.0 / market_price) - 1.0
    
    # Kelly Formel: f = (p * (b + 1) - 1) / b
    # wobei p = ai_probability, b = net_odds
    kelly_f = (ai_probability * (net_odds + 1.0) - 1.0) / net_odds
    
    # Fractional Kelly anwenden (konservativer)
    fractional_kelly = kelly_f * KELLY_FRACTION
    
    # Anpassen basierend auf Confidence
    adjusted_kelly = fractional_kelly * confidence
    
    # Hard-Cap bei 50% des Kapitals
    capped_kelly = min(adjusted_kelly, MAX_CAPITAL_FRACTION)
    
    # Berechne Einsatz
    stake = max(0.0, capped_kelly * capital)
    
    # Erwarteter Gewinn: E[X] = p * gewinn - (1-p) * verlust
    expected_value = ai_probability * (stake * net_odds) - (1 - ai_probability) * stake
    
    # Entscheidung
    if capped_kelly > 0.01 and ai_probability > market_price * 1.1:  # Mindestens 10% Edge
        action = "YES"
    elif capped_kelly < -0.01:
        action = "NO"
    else:
        action = "PASS"
        stake = 0.0
    
    return TradingRecommendation(
        action=action,
        stake_usdc=round(stake, 2),
        kelly_fraction=round(capped_kelly, 4),
        expected_value=round(expected_value, 2),
        market_question=""
    )


# ============================================================================
# MAIN ANALYSIS LOGIC
# ============================================================================

def analyze_and_recommend(market: MarketData) -> None:
    """
    Führt die komplette Analyse für einen Markt durch und gibt eine Empfehlung aus.
    
    Args:
        market: Das zu analysierende MarketData-Objekt
    """
    print("=" * 80)
    print(f"📊 MARKT: {market.question}")
    print(f"💰 Volumen: ${market.volume:,.0f}")
    print(f"💲 Aktueller Yes-Preis: {market.yes_price:.2%}")
    print("-" * 80)
    
    # KI-Analyse
    ai_analysis = analyze_market_with_ai(market)
    
    if not ai_analysis:
        print("⚠️  KI-Analyse fehlgeschlagen - SKIP\n")
        return
    
    print(f"🧠 KI-Wahrscheinlichkeit: {ai_analysis.estimated_probability:.2%}")
    print(f"🎯 Confidence: {ai_analysis.confidence_score:.2%}")
    print(f"💭 Begründung: {ai_analysis.reasoning[:200]}...")
    print("-" * 80)
    
    # Kelly-Berechnung
    recommendation = calculate_kelly_stake(
        ai_probability=ai_analysis.estimated_probability,
        market_price=market.yes_price,
        confidence=ai_analysis.confidence_score,
        capital=TOTAL_CAPITAL
    )
    recommendation.market_question = market.question
    
    # Ausgabe der Empfehlung
    print(f"🎲 EMPFEHLUNG: {recommendation.action}")
    print(f"💵 Einsatz: {recommendation.stake_usdc:.2f} USDC ({recommendation.kelly_fraction:.2%} des Kapitals)")
    print(f"📈 Erwarteter Gewinn: {recommendation.expected_value:+.2f} USDC")
    
    # Edge-Berechnung
    edge = ai_analysis.estimated_probability - market.yes_price
    print(f"⚡ Edge: {edge:+.2%}")
    
    if recommendation.action == "YES":
        print("✅ VALUE BET GEFUNDEN! Kaufe YES-Shares")
    elif recommendation.action == "NO":
        print("🔴 Kaufe NO-Shares")
    else:
        print("⏭️  Kein ausreichender Edge - PASS")
    
    print("=" * 80)
    print()


def main():
    """Hauptfunktion des Bots."""
    print("\n" + "=" * 80)
    print("🤖 POLYMARKET AI VALUE BET BOT")
    print("=" * 80)
    print(f"💰 Gesamtkapital: ${TOTAL_CAPITAL:,.2f} USDC")
    print(f"📊 Kelly Fraction: {KELLY_FRACTION:.0%}")
    print(f"🛡️  Max. Kapitaleinsatz pro Trade: {MAX_CAPITAL_FRACTION:.0%}")
    print("=" * 80)
    print()
    
    # Hole Märkte
    markets = fetch_active_markets(limit=10)
    
    if not markets:
        print("❌ Keine Märkte gefunden!")
        return
    
    # Analysiere Top-Märkte
    print(f"🔍 Analysiere {len(markets)} Märkte...\n")
    
    for i, market in enumerate(markets, 1):
        print(f"\n[{i}/{len(markets)}]")
        analyze_and_recommend(market)
    
    print("\n" + "=" * 80)
    print("✅ Analyse abgeschlossen!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
