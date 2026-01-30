#!/usr/bin/env python3
"""
Polymarket AI Value Bet Bot

Ein Bot zur Identifizierung von Value Bets auf Polymarket durch Kombination von:
- Marktdaten aus der Polymarket Gamma API (REST)
- KI-gestützte Wahrscheinlichkeitsschätzung via Google Gemini mit Search Grounding
- Kelly-Kriterium zur Positionsgrößenbestimmung (max. 50% des Kapitals)
"""

import os
import sys
import json
import logging
from typing import Optional, List
from datetime import datetime

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import requests
from dateutil import parser as date_parser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


# ============================================================================
# KONFIGURATION
# ============================================================================

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "1000"))

POLYMARKET_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"  # Gamma REST API
MIN_VOLUME = 15000  # Mindestvolumen in USD für Markt-Selektion
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
    Holt aktive Märkte von der Polymarket Gamma API (REST).
    
    Args:
        limit: Maximale Anzahl der zurückzugebenden Märkte
        
    Returns:
        Liste von MarketData-Objekten (leer bei Fehler)
    """
    try:
        logger.info(f"📡 Verbinde mit Polymarket Gamma API...")
        
        # REST API Query parameters
        params = {
            "closed": "false",  # Only active markets
            "limit": limit,
            "offset": 0,
            "order": "volume",  # Sort by volume
            "ascending": "false"  # Descending order
        }
        
        # GET Request to Gamma REST API
        response = requests.get(
            POLYMARKET_GAMMA_API_URL,
            params=params,
            headers={
                "Content-Type": "application/json"
            },
            timeout=10
        )
        
        # Prüfe HTTP Status
        if response.status_code != 200:
            logger.warning(f"⚠️  Gamma API HTTP Fehler: {response.status_code}")
            logger.warning(f"⚠️  Response: {response.text[:200]}")
            return []
        
        # Parse JSON Response
        data = response.json()
        
        # Extrahiere Märkte - REST API returns list directly or in 'data' field
        if isinstance(data, list):
            market_data_list = data
        elif isinstance(data, dict):
            market_data_list = data.get("data", data.get("markets", []))
        else:
            logger.warning(f"⚠️  Unerwartetes Response-Format: {type(data)}")
            return []
        
        if not market_data_list:
            logger.warning(f"⚠️  Keine Märkte von Gamma API empfangen")
            return []
        
        logger.info(f"📥 {len(market_data_list)} Märkte von Gamma API empfangen")
        
        markets = []
        
        # Debug-Zähler
        parse_error_count = 0
        extreme_price_count = 0
        expired_count = 0
        
        for market in market_data_list:
            # Filter by volume - skip markets with low volume
            volume_raw = market.get('volume')
            try:
                volume = float(volume_raw) if volume_raw is not None else 0.0
            except (ValueError, TypeError):
                continue
            
            # Skip markets below minimum volume threshold
            if volume < MIN_VOLUME:
                continue
            
            # Filter by end_date - skip markets that have already ended
            # REST API uses 'close_time', GraphQL uses 'endDate'
            end_date_str = market.get('close_time') or market.get('endDate')
            if end_date_str:
                try:
                    # Parse the end date (ISO 8601 format)
                    end_date = date_parser.parse(end_date_str)
                    now = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.now()
                    
                    # Skip markets that have already ended
                    if end_date < now:
                        expired_count += 1
                        question_str = str(market.get('question', 'N/A'))
                        # Only log if it's significantly old (more than 1 day)
                        if (now - end_date).days > 1:
                            logger.info(f"⏭️  Skipping expired market: {question_str[:60]}... (ended {end_date.date()})")
                        continue
                except Exception as e:
                    # If we can't parse the date, log the error but don't skip the market
                    question_str = str(market.get('question', 'N/A'))
                    logger.warning(f"⚠️  Could not parse end_date for market: {question_str[:50]} - Value: {end_date_str}, Error: {e}")
            
            # Get the question/description
            question = market.get('question', '')
            description = market.get('description', '')
            
            # Parse outcome prices
            # REST API uses 'outcome_prices', GraphQL uses 'outcomePrices'
            # Both can be either a JSON string '["0.65", "0.35"]' or a list [0.65, 0.35]
            try:
                outcome_prices_raw = market.get('outcome_prices') or market.get('outcomePrices')
                
                # Parse the JSON string if it exists
                if outcome_prices_raw:
                    if isinstance(outcome_prices_raw, str):
                        outcome_prices = json.loads(outcome_prices_raw)
                    elif isinstance(outcome_prices_raw, list):
                        outcome_prices = outcome_prices_raw
                    else:
                        outcome_prices = [0.5, 0.5]
                    
                    # Get the first outcome price (typically YES)
                    if len(outcome_prices) > 0:
                        yes_price = float(outcome_prices[0])
                    else:
                        yes_price = 0.5
                else:
                    yes_price = 0.5
                    
            except (ValueError, TypeError, json.JSONDecodeError, IndexError) as e:
                parse_error_count += 1
                question_str = str(question) if question else 'N/A'
                logger.warning(f"⚠️  Konnte Preis nicht parsen für Markt: {question_str[:50]} - Fehler: {e}")
                logger.warning(f"    outcome_prices Wert: {market.get('outcome_prices') or market.get('outcomePrices')}")
                continue
            
            # Check: Spread (price extremes) - filter out markets with low liquidity
            # Prices too close to 0 or 1 indicate liquidity risk
            if not (0.15 <= yes_price <= 0.85):
                extreme_price_count += 1
                question_str = str(question) if question else 'N/A'
                logger.info(f"⏭️  Skipping {question_str[:60]}: Preis zu extrem ({yes_price:.2f}), Liquiditätsrisiko.")
                continue
            
            # Get market identifier
            # REST API uses 'id', GraphQL uses 'conditionId', fallback to 'slug'
            market_slug = market.get('id') or market.get('conditionId') or market.get('slug') or ''
            
            try:
                markets.append(MarketData(
                    question=question,
                    description=description,
                    market_slug=market_slug,
                    yes_price=yes_price,
                    volume=volume,
                    end_date=market.get('close_time') or market.get('endDate')
                ))
            except Exception as e:
                parse_error_count += 1
                logger.warning(f"⚠️  Konnte MarketData nicht erstellen: {e}")
                continue
        
        # Debug-Ausgabe
        logger.info(f"\n📊 Markt-Filter Statistik:")
        logger.info(f"   - Gesamt empfangen: {len(market_data_list)}")
        logger.info(f"   - Abgelaufen (endDate überschritten): {expired_count}")
        logger.info(f"   - Preis zu extrem (außerhalb 0.15-0.85): {extreme_price_count}")
        logger.info(f"   - Parse-Fehler: {parse_error_count}")
        logger.info(f"   - ✅ Qualifiziert: {len(markets)}\n")
        
        return markets
        
    except requests.exceptions.ConnectionError as e:
        error_msg = str(e)
        logger.error(f"⚠️  Gamma API Verbindungsfehler: {error_msg}")
        logger.info(f"ℹ️  Die Polymarket Gamma API ist in dieser Umgebung nicht erreichbar.")
        logger.info(f"ℹ️  Dies kann aufgrund von Netzwerkbeschränkungen auftreten.")
        logger.info(f"ℹ️  Bitte stellen Sie sicher, dass:")
        logger.info(f"   1. Sie eine Internetverbindung haben")
        logger.info(f"   2. Die Domain 'gamma-api.polymarket.com' erreichbar ist")
        logger.info(f"   3. Keine Firewall die Verbindung blockiert")
        logger.info(f"\n💡 Tipp: Führen Sie 'curl https://gamma-api.polymarket.com/markets' aus, um die Erreichbarkeit zu testen.\n")
        return []
    except requests.exceptions.Timeout:
        logger.warning(f"⚠️  Gamma API Timeout - keine Antwort innerhalb von 10 Sekunden")
        return []
    except Exception as e:
        error_msg = str(e)
        logger.error(f"⚠️  Unerwarteter Fehler: {error_msg}")
        
        # For other errors, print traceback
        import traceback
        traceback.print_exc()
        
        return []


# ============================================================================
# GOOGLE GEMINI AI INTEGRATION
# ============================================================================

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def _generate_gemini_response(client: genai.Client, prompt: str, response_schema: type[BaseModel]) -> dict:
    """
    Helper function to generate Gemini response with automatic retry on rate limits.
    
    Args:
        client: Configured Gemini client
        prompt: The prompt to send to Gemini
        response_schema: Pydantic model class to use as schema (used for validation only now)
        
    Returns:
        Parsed JSON response as dictionary
        
    Raises:
        Exception: On API errors (will be retried automatically)
    """
    # Note: Controlled generation (response_schema) is not supported with Search tool.
    # We must parse the JSON manually.
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            # response_mime_type='application/json',  # Not supported with Search tool
            # response_schema=response_schema         # Not supported with Search tool
        )
    )

    text_response = response.text

    # Clean up markdown code blocks if present
    if "```json" in text_response:
        text_response = text_response.split("```json")[1].split("```")[0]
    elif "```" in text_response:
        text_response = text_response.split("```")[1].split("```")[0]

    return json.loads(text_response.strip())


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

Gib deine Analyse als reines JSON mit folgenden Feldern zurück (kein Markdown, nur JSON):
{{
  "estimated_probability": 0.0-1.0,
  "confidence_score": 0.0-1.0,
  "reasoning": "Ausführliche Begründung mit Quellen"
}}

Wichtig: 
- Sei objektiv und faktenbezogen
- Berücksichtige aktuelle Entwicklungen
- Gib einen realistischen Confidence-Score an
"""
        
        logger.info(f"🤖 Analysiere mit Gemini: {market.question[:60]}...")
        
        # Use structured output with retry logic
        result = _generate_gemini_response(client, prompt, AIAnalysis)
        
        # Create AIAnalysis object from parsed JSON
        return AIAnalysis(**result)
        
    except Exception as e:
        logger.error(f"❌ Fehler bei KI-Analyse: {e}")
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
    logger.info("=" * 80)
    logger.info(f"📊 MARKT: {market.question}")
    logger.info(f"💰 Volumen: ${market.volume:,.0f}")
    logger.info(f"💲 Aktueller Yes-Preis: {market.yes_price:.2%}")
    logger.info("-" * 80)
    
    # KI-Analyse
    ai_analysis = analyze_market_with_ai(market)
    
    if not ai_analysis:
        logger.warning("⚠️  KI-Analyse fehlgeschlagen - SKIP\n")
        return
    
    logger.info(f"🧠 KI-Wahrscheinlichkeit: {ai_analysis.estimated_probability:.2%}")
    logger.info(f"🎯 Confidence: {ai_analysis.confidence_score:.2%}")
    logger.info(f"💭 Begründung: {ai_analysis.reasoning[:200]}...")
    logger.info("-" * 80)
    
    # Kelly-Berechnung
    recommendation = calculate_kelly_stake(
        ai_probability=ai_analysis.estimated_probability,
        market_price=market.yes_price,
        confidence=ai_analysis.confidence_score,
        capital=TOTAL_CAPITAL
    )
    recommendation.market_question = market.question
    
    # Ausgabe der Empfehlung
    logger.info(f"🎲 EMPFEHLUNG: {recommendation.action}")
    logger.info(f"💵 Einsatz: {recommendation.stake_usdc:.2f} USDC ({recommendation.kelly_fraction:.2%} des Kapitals)")
    logger.info(f"📈 Erwarteter Gewinn: {recommendation.expected_value:+.2f} USDC")
    
    # Edge-Berechnung
    edge = ai_analysis.estimated_probability - market.yes_price
    logger.info(f"⚡ Edge: {edge:+.2%}")
    
    if recommendation.action == "YES":
        logger.info("✅ VALUE BET GEFUNDEN! Kaufe YES-Shares")
    elif recommendation.action == "NO":
        logger.info("🔴 Kaufe NO-Shares")
    else:
        logger.info("⏭️  Kein ausreichender Edge - PASS")
    
    logger.info("=" * 80)
    logger.info("")


def main():
    """Hauptfunktion des Bots."""
    # Check for API key when running as main
    if not GEMINI_API_KEY:
        logger.error("❌ Fehler: GEMINI_API_KEY nicht in .env gefunden!")
        sys.exit(1)
    
    logger.info("\n" + "=" * 80)
    logger.info("🤖 POLYMARKET AI VALUE BET BOT")
    logger.info("=" * 80)
    logger.info(f"💰 Gesamtkapital: ${TOTAL_CAPITAL:,.2f} USDC")
    logger.info(f"📊 Kelly Fraction: {KELLY_FRACTION:.0%}")
    logger.info(f"🛡️  Max. Kapitaleinsatz pro Trade: {MAX_CAPITAL_FRACTION:.0%}")
    logger.info("=" * 80)
    logger.info("")
    
    # Hole Märkte
    markets = fetch_active_markets(limit=10)
    
    if not markets:
        logger.error("❌ Keine Märkte gefunden!")
        return
    
    # Analysiere Top-Märkte
    logger.info(f"🔍 Analysiere {len(markets)} Märkte...\n")
    
    for i, market in enumerate(markets, 1):
        logger.info(f"\n[{i}/{len(markets)}]")
        analyze_and_recommend(market)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ Analyse abgeschlossen!")
    logger.info("=" * 80 + "\n")


if __name__ == "__main__":
    main()
