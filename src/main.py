#!/usr/bin/env python3
# isort: skip_file
"""
Polymarket AI Value Bet Bot - Automated 24/7 System

Ein Bot zur Identifizierung von Value Bets auf Polymarket durch Kombination von:
- Marktdaten aus der Polymarket Gamma API (REST/GraphQL)
- KI-gestützte Wahrscheinlichkeitsschätzung via Google Gemini mit Search Grounding
- Kelly-Kriterium zur Positionsgrößenbestimmung
- Automatisches Portfolio-Tracking und Reporting
"""

import json
import logging
import logging.handlers
import math
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Add project root to sys.path to allow imports from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Internal modules
from src import (  # noqa: E402
    ai_decisions_generator,
    dashboard,
    database,
    git_integration,
)

# ============================================================================
# KONFIGURATION
# ============================================================================

# Configure logging with robust error handling

# Ensure logs directory exists with correct permissions
log_dir = pathlib.Path("logs")
log_dir.mkdir(exist_ok=True)

# Try to fix permissions if we can
try:
    os.chmod(log_dir, 0o755)
except Exception:
    pass

log_file = log_dir / "bot.log"

# Remove existing log file if it has permission issues
if log_file.exists():
    try:
        with open(log_file, "a") as test_file:
            pass
    except PermissionError:
        print(f"⚠️ Warning: Removing log file with permission issues: {log_file}")
        try:
            log_file.unlink()
        except Exception:
            print(f"❌ Cannot remove log file. Please run: sudo rm {log_file}")
            print("   Then restart the service.")
            sys.exit(1)

# Configure logging with both console and file output
log_handlers: List[logging.Handler] = [
    logging.StreamHandler(),  # Console output
    logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
        delay=True,  # Lazy file creation to avoid permission issues
    ),
]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=log_handlers,
)
logger = logging.getLogger(__name__)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API URLs
# REST API für Market Discovery (unverändert)
POLYMARKET_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

# NEU: Goldsky Markets Subgraph für GraphQL (ersetzt deprecated Gamma GraphQL)
GRAPHQL_URL = "https://api.goldsky.com/api/public/project_clrb8pu7r0abk01w14w7o5rkl/subgraphs/polymarket-markets/latest/gn"

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

# API Rate Limit (Gemini Free Tier is often 15 RPM)
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "15"))

# ============================================================================
# DATENMODELLE
# ============================================================================


class MarketData(BaseModel):
    """Datenmodell für einen Polymarket-Markt."""

    question: str = Field(..., description="Die Marktfrage")
    description: str = Field(default="", description="Detaillierte Marktbeschreibung")
    market_slug: str = Field(..., description="Eindeutige ID des Marktes (conditionId)")
    url_slug: str = Field(..., description="URL-friendly slug")
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
    ai_reasoning: Optional[str] = None
    edge: Optional[float] = None


# ============================================================================
# UTILS
# ============================================================================


class RateLimiter:
    """Manages API rate limits using a sliding window."""

    def __init__(self, max_requests_per_minute=15):
        self.max_requests = max_requests_per_minute
        self.requests = []

    def wait_if_needed(self):
        now = datetime.now()
        # Remove requests older than 1 minute
        self.requests = [r for r in self.requests if r > now - timedelta(minutes=1)]

        # NEU: Log Rate Limiter Status
        logger.debug(f"🔍 Rate Limiter: {len(self.requests)}/{self.max_requests} requests in window")

        if len(self.requests) >= self.max_requests:
            # Sort requests just in case
            self.requests.sort()
            oldest = self.requests[0]
            # Time passed since oldest request
            elapsed = (now - oldest).total_seconds()
            sleep_time = 60 - elapsed

            if sleep_time > 0:
                logger.warning(
                    f"⏳ Rate Limit Hit: {len(self.requests)}/{self.max_requests} "
                    f"requests. Sleeping {sleep_time:.2f}s"
                )
                logger.warning(f"⏳ Oldest request at: {oldest.isoformat()}")
                time.sleep(sleep_time + 0.5)  # Add small buffer

        self.requests.append(datetime.now())


# Global Rate Limiter instance
rate_limiter = RateLimiter(max_requests_per_minute=API_RATE_LIMIT)

# ============================================================================
# RESOLUTION LOGIC
# ============================================================================


def check_and_resolve_bets():  # noqa: C901
    """Prüft abgelaufene Wetten auf Resolution und aktualisiert Resultate."""
    try:
        active_bets = database.get_active_bets()
        if not active_bets:
            # Check for archived but unresolved bets even if no active bets
            pass

        logger.info("🔍 Checking resolution status...")

        bets_to_check = []
        for bet in active_bets:
            # Check date logic
            end_date_val = bet.get("end_date")
            is_expired = False

            # Helper to parse date
            end_date_obj = None
            if isinstance(end_date_val, datetime):
                end_date_obj = end_date_val
            elif isinstance(end_date_val, str):
                try:
                    end_date_obj = date_parser.parse(end_date_val)
                except Exception:
                    end_date_obj = datetime.now(timezone.utc)

            # Ensure timezone awareness for comparison
            if end_date_obj and end_date_obj.tzinfo is None:
                end_date_obj = end_date_obj.replace(tzinfo=timezone.utc)

            if end_date_obj:
                now = datetime.now(timezone.utc)
                if end_date_obj < now:
                    is_expired = True

            # If expired, we MUST resolve or archive
            if is_expired:
                bets_to_check.append(bet)

        # Also add unresolved archived bets to check list
        # We handle them separately but logic is similar (need to fetch market data)
        archived_unresolved = database.get_unresolved_archived_bets()

        # Combined check
        # We need to map back which bet is which (active vs archived)
        # Use a wrapper or just process separately.
        # Processing separately is safer.

        # 1. Process ACTIVE bets
        if bets_to_check:
            process_resolution_for_bets(bets_to_check, is_archived=False)

        # 2. Process ARCHIVED bets
        if archived_unresolved:
            logger.info(
                f"🔍 Checking {len(archived_unresolved)} archived unresolved bets..."
            )
            process_resolution_for_bets(archived_unresolved, is_archived=True)

    except Exception as exc:
        logger.error(f"❌ Error during resolution check: {exc}", exc_info=True)


def process_resolution_for_bets(bets: List[Dict], is_archived: bool):  # noqa: C901
    """Helper to process resolution for a list of bets."""
    unique_slugs = list(set(b["market_slug"] for b in bets))

    resolved_markets = execute_batched_query(
        unique_slugs,
        lambda safe_id: f"market(id: {safe_id}) {{ closed resolvedBy outcomes {{ price }} }}",
    )

    bets_to_close = []
    bets_to_update = []

    # Process Bets
    for bet in bets:
        market_data = resolved_markets.get(bet["market_slug"])
        resolved_by = market_data.get("resolvedBy") if market_data else None

        if market_data and resolved_by:
            # Resolved
            outcomes = market_data.get("outcomes", [])
            prices = [float(o.get("price", 0)) for o in outcomes if o] if outcomes else []  # type: ignore

            actual_outcome = None
            if prices and len(prices) >= 2:
                p_yes = float(prices[0])
                if p_yes > 0.9:
                    actual_outcome = "YES"
                elif p_yes < 0.1:
                    actual_outcome = "NO"

            if actual_outcome:
                stake = float(bet["stake_usdc"])
                entry = float(bet["entry_price"])

                if bet["action"] == actual_outcome:
                    if entry > 0:
                        profit = stake * ((1.0 / entry) - 1.0)
                    else:
                        profit = 0.0
                else:
                    profit = -stake

                if is_archived:
                    bets_to_update.append((bet["archive_id"], actual_outcome, profit))
                else:
                    bets_to_close.append((bet["bet_id"], actual_outcome, profit))

                logger.info(
                    f"✅ Bet resolved: {bet['action']} -> {actual_outcome} (P/L: ${profit:.2f})"
                )
            else:
                logger.warning(f"⚠️ Market resolved but outcome unclear: {prices}")
                # If active and resolved but unclear, maybe we should archive as unresolved?
                # For now, leave it.

        else:
            # Not resolved yet
            if not is_archived:
                # Active bet expired but not resolved -> Archive as PENDING
                # Check if strictly expired
                end_date = bet.get("end_date")
                if end_date:
                    if isinstance(end_date, str):
                        try:
                            end_date = date_parser.parse(end_date).replace(
                                tzinfo=timezone.utc
                            )
                        except Exception:
                            end_date = datetime.now(timezone.utc)
                    elif end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)

                    if end_date < datetime.now(timezone.utc):
                        database.archive_bet_without_resolution(bet["bet_id"])

    if bets_to_close:
        database.close_bets_batch(bets_to_close)

    if bets_to_update:
        database.update_archived_bets_outcome_batch(bets_to_update)


# ============================================================================
# API HELPERS
# ============================================================================


def graphql_request_with_retry(query: str, max_retries: int = 3) -> Optional[dict]:
    """
    Führt GraphQL-Request mit exponentiellem Backoff bei Fehlern aus.
    Nutzt Goldsky Subgraph.
    """
    for attempt in range(max_retries):
        try:
            logger.debug(f"🔍 GraphQL Attempt {attempt + 1}/{max_retries}")
            logger.debug(f"🔍 GraphQL URL: {GRAPHQL_URL}")
            logger.debug(f"🔍 GraphQL Query (first 300 chars): {query[:300]}")

            response = requests.post(
                GRAPHQL_URL,
                json={"query": query},
                headers={"Content-Type": "application/json"},
                timeout=20,
            )

            # NEU: Detailliertes Response Logging
            logger.debug(f"🔍 GraphQL Status Code: {response.status_code}")
            logger.debug(f"🔍 GraphQL Response Headers: {dict(response.headers)}")

            if response.status_code == 200:
                response_data = response.json()
                logger.debug(f"🔍 GraphQL Response Keys: {response_data.keys() if response_data else 'None'}")
                return response_data
            elif response.status_code == 404:
                logger.error(f"❌ GraphQL 404 Error")
                logger.error(f"❌ Response Body: {response.text[:500]}")
                logger.error(f"❌ Query was: {query[:200]}")
                return None
            elif response.status_code in [429, 500, 502, 503, 504]:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"⚠️ GraphQL {response.status_code} - Retry in {wait_time}s")
                logger.warning(f"⚠️ Response: {response.text[:300]}")
                time.sleep(wait_time)
            else:
                logger.warning(f"⚠️ GraphQL HTTP {response.status_code}")
                logger.warning(f"⚠️ Response Body: {response.text[:500]}")
                return None

        except requests.exceptions.Timeout as e:
            logger.error(f"❌ GraphQL Timeout on attempt {attempt + 1}")
            logger.error(f"❌ Query: {query[:200]}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ GraphQL Connection Error: {str(e)}")
        except Exception as exc:
            logger.error(f"❌ GraphQL Error Type: {type(exc).__name__}")
            logger.error(f"❌ GraphQL Error: {exc}", exc_info=True)
            if attempt == max_retries - 1:
                return None
    return None


def execute_batched_query(
    slugs: List[str],
    query_fragment_fn: Callable[[str], str],
    chunk_size: int = 50,
) -> Dict[str, Any]:
    """
    Executes a batched GraphQL query by chunking the requests.

    Args:
        slugs: List of market slugs/IDs to query.
        query_fragment_fn: Function that takes a JSON-safe ID string and returns the GraphQL query part.
        chunk_size: Number of items per request.

    Returns:
        Dict mapping original slug to the returned data.
    """
    results = {}

    for i in range(0, len(slugs), chunk_size):
        end_idx = i + chunk_size
        chunk = slugs[i:end_idx]
        query_parts = []
        slug_map = {}

        for idx, slug in enumerate(chunk):
            alias = f"m_{idx}"
            slug_map[alias] = slug
            safe_id = json.dumps(slug)
            query_parts.append(f"{alias}: {query_fragment_fn(safe_id)}")

        if not query_parts:
            continue

        query = "query BatchQuery { " + " ".join(query_parts) + " }"

        try:
            data = graphql_request_with_retry(query)
            if not data or not data.get("data"):
                continue

            for alias, market_data in data["data"].items():
                if market_data:
                    original_slug = slug_map.get(alias)
                    if original_slug:
                        results[original_slug] = market_data
        except Exception as exc:
            logger.error(f"❌ Error during batch GraphQL query: {exc}")

    return results


def fetch_active_markets(limit: int = 20) -> List[MarketData]:  # noqa: C901
    """Fetches active markets from the Polymarket Gamma API.

    Retrieves open markets sorted by volume to identify potential trading opportunities.
    Filters out markets with low volume or invalid data.

    Args:
        limit: Maximum number of markets to fetch (default: 20).

    Returns:
        A list of MarketData objects representing active markets.
        Returns an empty list if the API call fails.
    """
    try:
        logger.info("📡 Verbinde mit Polymarket Gamma API...")
        params = {
            "closed": "false",
            "limit": limit,
            "offset": 0,
            "order": "volume",
            "ascending": "false",
        }

        response = requests.get(
            POLYMARKET_GAMMA_API_URL, params=params, timeout=10  # type: ignore
        )

        if response.status_code != 200:
            logger.warning(f"⚠️  Gamma API HTTP Fehler: {response.status_code}")
            return []

        data = response.json()
        market_data_list = (
            data
            if isinstance(data, list)
            else data.get("data", data.get("markets", []))
        )

        markets = []

        for market in market_data_list:
            volume_raw = market.get("volume")
            try:
                volume = float(volume_raw) if volume_raw is not None else 0.0
            except Exception:
                continue

            if volume < MIN_VOLUME:
                continue

            # Check end date
            end_date_str = market.get("close_time") or market.get("endDate")
            if end_date_str:
                try:
                    end_date = date_parser.parse(end_date_str)
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    if end_date < datetime.now(timezone.utc):
                        continue
                except Exception:
                    pass

            # Price parsing
            try:
                outcome_prices_raw = market.get("outcome_prices") or market.get(
                    "outcomePrices"
                )
                if outcome_prices_raw:
                    if isinstance(outcome_prices_raw, str):
                        outcome_prices = json.loads(outcome_prices_raw)
                    elif isinstance(outcome_prices_raw, list):
                        outcome_prices = outcome_prices_raw
                    else:
                        outcome_prices = [0.5, 0.5]

                    yes_price = (
                        float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5
                    )
                else:
                    yes_price = 0.5
            except Exception:
                continue

            # Filter Logic
            if not (MIN_PRICE <= yes_price <= MAX_PRICE):
                if volume < HIGH_VOLUME_THRESHOLD:
                    continue

            # Extract IDs
            market_slug = market.get("id") or market.get("conditionId") or ""
            # NEW: Extract URL slug (prefer slug, then id)
            url_slug = market.get("slug") or market.get("id") or ""

            markets.append(
                MarketData(
                    question=market.get("question", ""),
                    description=market.get("description", ""),
                    market_slug=market_slug,
                    url_slug=url_slug,
                    yes_price=yes_price,
                    volume=volume,
                    end_date=end_date_str,
                )
            )

        return markets

    except Exception as exc:
        logger.error(f"⚠️  Fehler beim Abrufen der Märkte: {exc}")
        return []


def fetch_missing_end_dates(  # noqa: C901
    markets: List[MarketData],
) -> List[MarketData]:
    """Retrieves missing end dates for markets using GraphQL.

    Some markets from the Gamma API might lack end dates. This function queries
    the Goldsky Subgraph to fill in this information, which is crucial for
    resolution tracking.

    Args:
        markets: List of MarketData objects to check.

    Returns:
        The updated list of MarketData objects with populated end dates where possible.
    """
    markets_missing_date = [m for m in markets if not m.end_date]
    if not markets_missing_date:
        return markets

    logger.info(
        f"📅 Fetching missing end dates for {len(markets_missing_date)} markets..."
    )

    slugs = [m.market_slug for m in markets_missing_date]
    data_map = execute_batched_query(
        slugs,
        lambda safe_id: f"market(id: {safe_id}) {{ end_date_iso }}",
    )

    for market in markets_missing_date:
        if market.market_slug in data_map:
            market_data = data_map[market.market_slug]
            if market_data and "end_date_iso" in market_data:
                market.end_date = market_data["end_date_iso"]

    return markets


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

    return volatility_score * 0.4 + volume_score * 0.4 + extreme_penalty * 0.2


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


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=8, max=30),
)
def _generate_gemini_response(client: genai.Client, prompt: str) -> tuple[dict, dict]:
    start_time = time.time()

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )

        logger.debug(f"🔍 Gemini Raw Response Type: {type(response)}")
        logger.debug(f"🔍 Gemini Has Text: {hasattr(response, 'text')}")

        response_time_ms = int((time.time() - start_time) * 1000)

        usage_meta = {
            "prompt_token_count": (
                response.usage_metadata.prompt_token_count
                if hasattr(response, "usage_metadata") and response.usage_metadata
                else 0
            ),
            "candidates_token_count": (
                response.usage_metadata.candidates_token_count
                if hasattr(response, "usage_metadata") and response.usage_metadata
                else 0
            ),
            "total_token_count": (
                response.usage_metadata.total_token_count
                if hasattr(response, "usage_metadata") and response.usage_metadata
                else 0
            ),
            "response_time_ms": response_time_ms,
        }

        text_response = response.text
        logger.debug(f"🔍 Gemini Raw Text (first 500 chars): {text_response[:500]}")

        if "```json" in text_response:
            text_response = text_response.split("```json")[1].split("```")[0]
        elif "```" in text_response:
            text_response = text_response.split("```")[1].split("```")[0]

        logger.debug(f"🔍 Extracted JSON Text: {text_response[:200]}")

        text_response = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text_response)
        try:
            parsed_data = json.loads(text_response.strip())
        except Exception:
            parsed_data = json.loads(text_response.strip(), strict=False)

        return parsed_data, usage_meta

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON Parse Error at position {e.pos}")
        logger.error(f"❌ Problematic text: {text_response}")
        logger.error(f"❌ Error message: {e.msg}")
        raise
    except Exception as e:
        logger.error(f"❌ Gemini API Error Type: {type(e).__name__}")
        logger.error(f"❌ Error Details: {str(e)}")
        logger.error(f"❌ Full Traceback:", exc_info=True)
        raise


def analyze_market_with_ai(market: MarketData) -> Optional[AIAnalysis]:
    """Analyzes a market using Google Gemini AI to estimate probability.

    Uses Gemini 2.0 Flash with Search Grounding to research the market question
    and estimate the probability of the 'YES' outcome.

    Args:
        market: The MarketData object containing the question and context.

    Returns:
        An AIAnalysis object with probability, confidence, and reasoning,
        or None if the API call fails.
    """
    try:
        logger.info(f"🤖 Starting AI Analysis for: {market.question[:60]}")
        logger.debug(f"🔍 Market Details - Slug: {market.market_slug}, Price: {market.yes_price}, Volume: {market.volume}")

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Analysiere folgende Wettfrage von Polymarket und schätze die Wahrscheinlichkeit ein:
        FRAGE: {market.question}
        BESCHREIBUNG: {market.description}
        AKTUELLER MARKTPREIS (Yes): {market.yes_price:.2%}
        Nutze Google Search für Fakten.
        Output JSON: {{ "estimated_probability": 0.0-1.0, "confidence_score": 0.0-1.0, "reasoning": "..." }}
        """

        logger.debug(f"🔍 Sending prompt ({len(prompt)} chars)")
        result, usage_meta = _generate_gemini_response(client, prompt)

        logger.info(f"✅ AI Analysis Success - Tokens: {usage_meta['total_token_count']}, Time: {usage_meta['response_time_ms']}ms")
        logger.debug(f"🔍 AI Result Keys: {result.keys() if result else 'None'}")

        database.log_api_usage(
            api_name="gemini",
            endpoint="generate_content",
            tokens_prompt=usage_meta["prompt_token_count"],
            tokens_response=usage_meta["candidates_token_count"],
            response_time_ms=usage_meta["response_time_ms"],
        )
        return AIAnalysis(**result)
    except Exception as exc:
        logger.error(f"❌ AI Analysis Failed for: {market.question[:60]}")
        logger.error(f"❌ Market Slug: {market.market_slug}")
        logger.error(f"❌ Exception Type: {type(exc).__name__}")
        logger.error(f"❌ Exception Details: {str(exc)}", exc_info=True)

        # Use existing error_logger
        from src.error_logger import log_api_error
        log_api_error(
            api_name="gemini",
            endpoint="analyze_market",
            error=exc,
            context={
                "market_slug": market.market_slug,
                "question": market.question[:100],
                "yes_price": market.yes_price,
                "volume": market.volume
            }
        )
        return None


def calculate_kelly_stake(
    ai_prob: float, price: float, conf: float, capital: float
) -> TradingRecommendation:
    """Calculates the optimal stake size using the Kelly Criterion.

    Determines whether to bet YES, NO, or PASS based on the calculated edge and
    expected value. Applies fractional Kelly and a confidence multiplier to
    manage risk.

    Args:
        ai_prob: The estimated probability of the 'YES' outcome (0.0-1.0).
        price: The current market price of 'YES' (0.0-1.0).
        conf: The AI's confidence score (0.0-1.0).
        capital: The total available capital for trading.

    Returns:
        A TradingRecommendation object containing the action, stake size, and expected value.
    """
    if price <= 0.001 or price >= 0.999:
        return TradingRecommendation(
            action="PASS",
            stake_usdc=0.0,
            kelly_fraction=0.0,
            expected_value=0.0,
            market_question="",
        )

    edge = ai_prob - price
    if abs(edge) < 0.10:
        return TradingRecommendation(
            action="PASS",
            stake_usdc=0.0,
            kelly_fraction=0.0,
            expected_value=0.0,
            market_question="",
        )

    if edge > 0:  # Long
        net_odds = (1.0 / price) - 1.0
        kelly_f = (ai_prob * (net_odds + 1.0) - 1.0) / net_odds
        action = "YES"
    else:  # Short
        no_price = 1.0 - price
        ai_no_prob = 1.0 - ai_prob
        net_odds = (1.0 / no_price) - 1.0
        kelly_f = (ai_no_prob * (net_odds + 1.0) - 1.0) / net_odds
        action = "NO"

    capped_kelly = min(
        max(kelly_f * KELLY_FRACTION * math.sqrt(conf), 0.0), MAX_CAPITAL_FRACTION
    )
    stake = capped_kelly * capital

    if action == "YES":
        ev = ai_prob * (stake * ((1.0 / price) - 1.0)) - (1 - ai_prob) * stake
    else:
        ev = (1 - ai_prob) * (stake * ((1.0 / (1 - price)) - 1.0)) - ai_prob * stake

    if ev <= 0:
        return TradingRecommendation(
            action="PASS",
            stake_usdc=0.0,
            kelly_fraction=0.0,
            expected_value=0.0,
            market_question="",
        )

    return TradingRecommendation(
        action=action,
        stake_usdc=round(stake, 2),
        kelly_fraction=round(capped_kelly, 4),
        expected_value=round(ev, 2),
        market_question="",
    )


def analyze_and_recommend(
    market: MarketData, capital: float
) -> Tuple[Optional[TradingRecommendation], Optional[Dict]]:
    """
    Analysiert Markt und gibt Empfehlung ODER Rejection-Daten zurück.
    Returns: (Recommendation, RejectionDict)
    """
    logger.info(
        f"📊 Analysiere: {market.question} (Vol: ${market.volume:,.0f}, Price: {market.yes_price:.2f})"
    )

    ai_analysis = analyze_market_with_ai(market)
    if not ai_analysis:
        return None, {
            "market_slug": market.market_slug,
            "url_slug": market.url_slug,
            "question": market.question,
            "market_price": market.yes_price,
            "volume": market.volume,
            "ai_probability": 0.0,
            "confidence_score": 0.0,
            "edge": 0.0,
            "rejection_reason": "AI_ANALYSIS_FAILED",
            "ai_reasoning": "Gemini API error or timeout",
            "end_date": market.end_date,
        }

    rec = calculate_kelly_stake(
        ai_analysis.estimated_probability,
        market.yes_price,
        ai_analysis.confidence_score,
        capital,
    )

    rec.market_question = market.question
    rec.ai_probability = ai_analysis.estimated_probability
    rec.confidence_score = ai_analysis.confidence_score
    rec.ai_reasoning = ai_analysis.reasoning
    edge = ai_analysis.estimated_probability - market.yes_price
    rec.edge = edge

    if rec.action == "PASS":
        if abs(edge) < 0.10:
            reason = "INSUFFICIENT_EDGE"
        elif rec.expected_value <= 0:
            reason = "NEGATIVE_EXPECTED_VALUE"
        elif market.yes_price <= 0.001 or market.yes_price >= 0.999:
            reason = "EXTREME_PRICE"
        else:
            reason = "KELLY_TOO_SMALL"

        logger.info(f"⏭️  PASS: {market.question[:40]}... (Reason: {reason})")
        return None, {
            "market_slug": market.market_slug,
            "url_slug": market.url_slug,
            "question": market.question,
            "market_price": market.yes_price,
            "volume": market.volume,
            "ai_probability": ai_analysis.estimated_probability,
            "confidence_score": ai_analysis.confidence_score,
            "edge": edge,
            "rejection_reason": reason,
            "ai_reasoning": ai_analysis.reasoning,
            "end_date": market.end_date,
        }
    else:
        logger.info(
            f"🎲 RECOMMENDATION: {rec.action} | Stake: ${rec.stake_usdc} | Edge: {edge:+.2%} | EV: ${rec.expected_value}"
        )
        return rec, None


# ============================================================================
# MAIN LOOPS
# ============================================================================


def single_run():
    """Einzelner 15-Minuten-Cycle"""
    logger.info("🎬 Start Single Run...")
    run_start_time = datetime.now(timezone.utc)
    capital = database.get_current_capital()
    logger.info(f"💰 Verfügbares Kapital: ${capital:.2f}")

    check_and_resolve_bets()

    raw_markets = fetch_active_markets(limit=FETCH_MARKET_LIMIT)
    raw_markets = fetch_missing_end_dates(raw_markets)
    top_markets = pre_filter_markets(raw_markets, top_n=TOP_MARKETS_TO_ANALYZE)

    active_slugs = database.get_active_bet_slugs()

    rejections_to_insert = []
    active_bets_to_insert = []

    for i, market in enumerate(top_markets):
        if market.market_slug in active_slugs:
            logger.info(
                f"⏭️  Bereits aktive Wette für: {market.market_slug}. Skipping."
            )
            continue

        rate_limiter.wait_if_needed()

        rec, rejection = analyze_and_recommend(market, capital)

        if rejection:
            rejections_to_insert.append(rejection)

        if rec and rec.action != "PASS":
            active_bets_to_insert.append(
                {
                    "market_slug": market.market_slug,
                    "url_slug": market.url_slug,
                    "question": market.question,
                    "action": rec.action,
                    "stake_usdc": rec.stake_usdc,
                    "entry_price": market.yes_price,
                    "ai_probability": rec.ai_probability,
                    "confidence_score": rec.confidence_score,
                    "expected_value": rec.expected_value,
                    "edge": rec.edge,
                    "ai_reasoning": rec.ai_reasoning,
                    "end_date": market.end_date,
                }
            )
            active_slugs.add(market.market_slug)

    # Batch Insert Active Bets
    if active_bets_to_insert:
        database.insert_active_bets_batch(active_bets_to_insert)

    # Batch Insert Rejections
    if rejections_to_insert:
        database.insert_rejected_markets_batch(rejections_to_insert)

    logger.info("📝 Updating dashboard...")
    dashboard.generate_dashboard()
    ai_decisions_generator.generate_ai_decisions_file()
    git_integration.push_dashboard_update()
    database.set_last_run_timestamp(run_start_time)
    logger.info("✅ Run completed. Sleeping 15 minutes...")


def main_loop():
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.error("❌ GEMINI_API_KEY nicht gesetzt!")
        sys.exit(1)

    database.init_database()
    logger.info("🚀 Starting Polymarket Bot Main Loop (15min Interval)")

    while True:
        try:
            single_run()
            time.sleep(900)
        except KeyboardInterrupt:
            logger.info("🛑 Shutdown requested")
            break
        except Exception as exc:
            logger.error(f"❌ Run failed: {exc}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
