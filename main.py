#!/usr/bin/env python3
"""
Polymarket AI Value Bet Bot - Automated 24/7 System

Ein Bot zur Identifizierung von Value Bets auf Polymarket durch Kombination von:
- Marktdaten aus der Polymarket Gamma API (REST/GraphQL)
- KI-gestützte Wahrscheinlichkeitsschätzung via Google Gemini mit Search Grounding
- Kelly-Kriterium zur Positionsgrößenbestimmung
- Automatisches Portfolio-Tracking und Reporting
"""

import os
import sys
import json
import logging
import logging.handlers
import time
import math
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import requests
from dateutil import parser as date_parser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Internal modules
import database
import dashboard
import git_integration

# ============================================================================
# KONFIGURATION
# ============================================================================

# Configure logging
# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Configure logging with both console and file output
log_handlers = [
    logging.StreamHandler(),  # Console output
    logging.handlers.RotatingFileHandler(
        'logs/bot.log',
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding='utf-8'
    )
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API URLs
POLYMARKET_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
GRAPHQL_URL = "https://gamma-api.polymarket.com/query"

# Trading Strategy Params
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "10000"))
KELLY_FRACTION = 0.25
MAX_CAPITAL_FRACTION = 0.5
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.05"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.95"))
HIGH_VOLUME_THRESHOLD = float(os.getenv("HIGH_VOLUME_THRESHOLD", "50000"))

# Execution Params
FETCH_MARKET_LIMIT = int(os.getenv("FETCH_MARKET_LIMIT", "100"))
TOP_MARKETS_TO_ANALYZE = int(os.getenv("TOP_MARKETS_TO_ANALYZE", "15"))


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
    estimated_probability: float = Field(..., ge=0.0, le=1.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., description="Begründung der KI")

class TradingRecommendation(BaseModel):
    """Datenmodell für eine Handelsempfehlung."""
    action: str = Field(..., description="Empfehlung: YES, NO oder PASS")
    stake_usdc: float = Field(..., description="Empfohlener Einsatz in USDC")
    kelly_fraction: float = Field(..., description="Kelly-Fraction des Kapitals")
    expected_value: float = Field(..., description="Erwarteter Gewinn")
    market_question: str = Field(..., description="Die Marktfrage")
    # Optional fields for DB storage
    ai_probability: Optional[float] = None
    confidence_score: Optional[float] = None


# ============================================================================
# RESOLUTION LOGIC
# ============================================================================

def check_and_resolve_bets():
    """Prüft abgelaufene Wetten auf Resolution und aktualisiert Resultate."""
    try:
        active_bets = database.get_active_bets()
        if not active_bets:
            return

        logger.info(f"🔍 Prüfe {len(active_bets)} aktive Wetten auf Resolution...")
        
        for bet in active_bets:
            # Check date logic
            end_date_val = bet['end_date']
            is_expired = False

            if end_date_val:
                if isinstance(end_date_val, str):
                    try:
                        end_date_obj = date_parser.parse(end_date_val)
                    except:
                        end_date_obj = datetime.now() # Fallback
                else:
                    end_date_obj = end_date_val

                # Compare with now (timezone aware if possible)
                now = datetime.now(end_date_obj.tzinfo) if end_date_obj.tzinfo else datetime.now()
                if end_date_obj < now:
                    is_expired = True

            # Nur abgelaufene prüfen (oder wenn kein Datum vorhanden)
            if not is_expired and end_date_val is not None:
                continue

            # GraphQL Query
            query = """
            query GetMarketResolution($id: ID!) {
              market(id: $id) {
                closed
                resolvedBy
                outcomePrices
              }
            }
            """

            response = requests.post(
                GRAPHQL_URL,
                json={'query': query, 'variables': {'id': bet['market_slug']}},
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code != 200:
                logger.warning(f"⚠️  GraphQL Fehler für Bet {bet['bet_id']}: {response.status_code}")
                continue

            data = response.json()
            market_data = data.get('data', {}).get('market', {})

            if not market_data:
                continue

            resolved_by = market_data.get('resolvedBy')

            if resolved_by:
                # Market is resolved. Check prices.
                prices = market_data.get('outcomePrices', [])

                actual_outcome = None
                if prices and len(prices) >= 2:
                    try:
                        p_yes = float(prices[0])
                        if p_yes > 0.9:
                            actual_outcome = "YES"
                        elif p_yes < 0.1:
                            actual_outcome = "NO"
                    except:
                        pass

                if actual_outcome:
                    # Calculate Profit/Loss
                    stake = bet['stake_usdc']
                    entry = bet['entry_price']

                    if bet['action'] == actual_outcome:
                        # WIN
                        if entry > 0:
                            profit = stake * ((1.0 / entry) - 1.0)
                        else:
                            profit = 0.0
                    else:
                        # LOSS
                        profit = -stake

                    # Close bet
                    database.close_bet(bet['bet_id'], actual_outcome, profit)
                    logger.info(f"✅ Bet {bet['bet_id']} resolved: {bet['action']} -> {actual_outcome} (P/L: ${profit:.2f})")
                else:
                    logger.warning(f"⚠️  Market resolved but outcome unclear: {prices}")

    except Exception as e:
        logger.error(f"❌ Error during resolution check: {e}")

# ============================================================================
# API HELPERS
# ============================================================================

def fetch_active_markets(limit: int = 20) -> List[MarketData]:
    """Holt aktive Märkte von der Polymarket Gamma API."""
    try:
        logger.info(f"📡 Verbinde mit Polymarket Gamma API...")
        params = {
            "closed": "false",
            "limit": limit,
            "offset": 0,
            "order": "volume",
            "ascending": "false"
        }
        
        response = requests.get(POLYMARKET_GAMMA_API_URL, params=params, timeout=10)
        
        if response.status_code != 200:
            logger.warning(f"⚠️  Gamma API HTTP Fehler: {response.status_code}")
            return []
        
        data = response.json()
        market_data_list = data if isinstance(data, list) else data.get("data", data.get("markets", []))
        
        markets = []
        
        for market in market_data_list:
            volume_raw = market.get('volume')
            try:
                volume = float(volume_raw) if volume_raw is not None else 0.0
            except:
                continue
            
            if volume < MIN_VOLUME:
                continue
            
            end_date_str = market.get('close_time') or market.get('endDate')
            if end_date_str:
                try:
                    end_date = date_parser.parse(end_date_str)
                    now = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.now()
                    if end_date < now:
                        continue
                except:
                    pass
            
            # Price parsing
            try:
                outcome_prices_raw = market.get('outcome_prices') or market.get('outcomePrices')
                if outcome_prices_raw:
                    if isinstance(outcome_prices_raw, str):
                        outcome_prices = json.loads(outcome_prices_raw)
                    elif isinstance(outcome_prices_raw, list):
                        outcome_prices = outcome_prices_raw
                    else:
                        outcome_prices = [0.5, 0.5]
                    
                    yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5
                else:
                    yes_price = 0.5
            except:
                continue
            
            # Filter Logic
            if not (MIN_PRICE <= yes_price <= MAX_PRICE):
                if volume < HIGH_VOLUME_THRESHOLD:
                    continue
            
            markets.append(MarketData(
                question=market.get('question', ''),
                description=market.get('description', ''),
                market_slug=market.get('id') or market.get('conditionId') or market.get('slug') or '',
                yes_price=yes_price,
                volume=volume,
                end_date=end_date_str
            ))
            
        return markets
        
    except Exception as e:
        logger.error(f"⚠️  Fehler beim Abrufen der Märkte: {e}")
        return []

def calculate_quick_edge(market: MarketData) -> float:
    """Schnelle Edge-Schätzung."""
    price_deviation = abs(market.yes_price - 0.5)
    volatility_score = 1.0 - (2 * price_deviation)
    volume_score = min(market.volume / 100000.0, 1.0)

    if 0.2 <= market.yes_price <= 0.8:
        extreme_penalty = 1.0
    elif 0.1 <= market.yes_price <= 0.9:
        extreme_penalty = 0.7
    else:
        extreme_penalty = 0.3

    return (volatility_score * 0.4 + volume_score * 0.4 + extreme_penalty * 0.2)

def pre_filter_markets(markets: List[MarketData], top_n: int = 10) -> List[MarketData]:
    """Vorselektion der Märkte."""
    if not markets:
        return []

    market_scores = []
    for market in markets:
        score = calculate_quick_edge(market)
        market_scores.append((market, score))

    market_scores.sort(key=lambda x: x[1], reverse=True)
    return [m for m, _ in market_scores[:top_n]]

# ============================================================================
# AI & ANALYSIS
# ============================================================================

@retry(retry=retry_if_exception_type(Exception), stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=8, max=30))
def _generate_gemini_response(client: genai.Client, prompt: str) -> dict:
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    text_response = response.text
    if "```json" in text_response:
        text_response = text_response.split("```json")[1].split("```")[0]
    elif "```" in text_response:
        text_response = text_response.split("```")[1].split("```")[0]

    text_response = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text_response)
    try:
        return json.loads(text_response.strip())
    except:
        return json.loads(text_response.strip(), strict=False)

def analyze_market_with_ai(market: MarketData) -> Optional[AIAnalysis]:
    """Analysiert einen Markt mit Gemini."""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Analysiere folgende Wettfrage von Polymarket und schätze die Wahrscheinlichkeit ein:
        FRAGE: {market.question}
        BESCHREIBUNG: {market.description}
        AKTUELLER MARKTPREIS (Yes): {market.yes_price:.2%}
        Nutze Google Search für Fakten.
        Output JSON: {{ "estimated_probability": 0.0-1.0, "confidence_score": 0.0-1.0, "reasoning": "..." }}
        """
        result = _generate_gemini_response(client, prompt)
        return AIAnalysis(**result)
    except Exception as e:
        logger.error(f"❌ Fehler bei KI-Analyse: {e}")
        return None

def calculate_kelly_stake(ai_prob: float, price: float, conf: float, capital: float) -> TradingRecommendation:
    """Berechnet Kelly-Einsatz."""
    if price <= 0.001 or price >= 0.999:
        return TradingRecommendation(action="PASS", stake_usdc=0.0, kelly_fraction=0.0, expected_value=0.0, market_question="")
        
    edge = ai_prob - price
    if abs(edge) < 0.10:
        return TradingRecommendation(action="PASS", stake_usdc=0.0, kelly_fraction=0.0, expected_value=0.0, market_question="")

    if edge > 0: # Long
        net_odds = (1.0 / price) - 1.0
        kelly_f = (ai_prob * (net_odds + 1.0) - 1.0) / net_odds
        action = "YES"
    else: # Short
        no_price = 1.0 - price
        ai_no_prob = 1.0 - ai_prob
        net_odds = (1.0 / no_price) - 1.0
        kelly_f = (ai_no_prob * (net_odds + 1.0) - 1.0) / net_odds
        action = "NO"

    capped_kelly = min(max(kelly_f * KELLY_FRACTION * math.sqrt(conf), 0.0), MAX_CAPITAL_FRACTION)
    stake = capped_kelly * capital
    
    # Expected Value
    if action == "YES":
        ev = ai_prob * (stake * ((1.0/price)-1.0)) - (1-ai_prob)*stake
    else:
        ev = (1-ai_prob) * (stake * ((1.0/(1-price))-1.0)) - ai_prob*stake

    if ev <= 0:
        return TradingRecommendation(action="PASS", stake_usdc=0.0, kelly_fraction=0.0, expected_value=0.0, market_question="")

    return TradingRecommendation(
        action=action, stake_usdc=round(stake, 2), kelly_fraction=round(capped_kelly, 4),
        expected_value=round(ev, 2), market_question=""
    )

def analyze_and_recommend(market: MarketData, capital: float) -> Optional[TradingRecommendation]:
    """Single Market Analysis Pipeline."""
    logger.info(f"📊 Analysiere: {market.question} (Vol: ${market.volume:,.0f}, Price: {market.yes_price:.2f})")
    
    ai_analysis = analyze_market_with_ai(market)
    if not ai_analysis:
        return None

    rec = calculate_kelly_stake(
        ai_analysis.estimated_probability,
        market.yes_price,
        ai_analysis.confidence_score,
        capital
    )
    rec.market_question = market.question
    
    # Attach AI stats for DB storage
    rec.ai_probability = ai_analysis.estimated_probability
    rec.confidence_score = ai_analysis.confidence_score
    
    if rec.action != "PASS":
        logger.info(f"🎲 RECOMMENDATION: {rec.action} | Stake: ${rec.stake_usdc} | EV: ${rec.expected_value}")
    
    return rec


# ============================================================================
# MAIN LOOPS
# ============================================================================

def single_run():
    """Einzelner 15-Minuten-Cycle"""
    logger.info("🎬 Start Single Run...")
    
    # 1. Load current capital from DB
    capital = database.get_current_capital()
    logger.info(f"💰 Verfügbares Kapital: ${capital:.2f}")
    
    # 2. Check and resolve pending bets
    check_and_resolve_bets()
    
    # 3. Fetch and analyze markets
    raw_markets = fetch_active_markets(limit=FETCH_MARKET_LIMIT)
    top_markets = pre_filter_markets(raw_markets, top_n=TOP_MARKETS_TO_ANALYZE)

    # 4. Analyze and save new bets
    active_slugs = {b['market_slug'] for b in database.get_active_bets()}

    for i, market in enumerate(top_markets):
        # Check if we already have an active bet on this market?
        if market.market_slug in active_slugs:
            logger.info(f"⏭️  Bereits aktive Wette für: {market.market_slug}. Skipping.")
            continue

        # Prevent Gemini Rate Limits
        time.sleep(3)

        rec = analyze_and_recommend(market, capital)

        if rec and rec.action != "PASS":
            database.insert_active_bet({
                'market_slug': market.market_slug,
                'question': market.question,
                'action': rec.action,
                'stake_usdc': rec.stake_usdc,
                'entry_price': market.yes_price,
                'ai_probability': rec.ai_probability,
                'confidence_score': rec.confidence_score,
                'expected_value': rec.expected_value,
                'end_date': market.end_date
            })
            active_slugs.add(market.market_slug)
    
    # 5. Update dashboard if needed
    if dashboard.should_update_dashboard():
        logger.info("📝 Updating dashboard...")
        dashboard.generate_dashboard()
        git_integration.push_dashboard_update()
    else:
        logger.info("✅ Dashboard up-to-date.")

def main_loop():
    """Infinite loop for 24/7 operation"""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        error_msg = (
            "❌ GEMINI_API_KEY nicht gesetzt (oder Placeholder gefunden)!\n"
            "   Bitte führe das Deployment-Skript erneut aus:\n"
            "   ./deploy_raspberry_pi.sh\n"
            "   Oder setze den Key manuell in der .env Datei:\n"
            "   https://aistudio.google.com/app/apikey"
        )
        logger.error(error_msg)
        print(error_msg, file=sys.stderr)  # Zusätzlicher stderr-Output für systemd
        sys.exit(1)

    database.init_database()

    logger.info("🚀 Starting Polymarket Bot Main Loop (15min Interval)")

    while True:
        try:
            single_run()
            logger.info("✅ Run completed. Sleeping 15 minutes...")
            time.sleep(900)
        except KeyboardInterrupt:
            logger.info("🛑 Shutdown requested")
            break
        except Exception as e:
            logger.error(f"❌ Run failed: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
