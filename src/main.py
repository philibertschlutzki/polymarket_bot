#!/usr/bin/env python3
# isort: skip_file
"""
Polymarket Bot - Continuous Processing System
v2.0 - Multi-threaded with Adaptive Rate Limiting

Transforms the bot from batch processing to a continuous stream:
1. Market Discovery Worker (5 min): Fetches and queues markets
2. Queue Processing Worker (Continuous): Analyzes markets with rate limiting
3. Health Monitor Worker (1 min): Tracks system stats
4. Resolution Worker (15 min): Resolves bets
"""

import json
import logging
import logging.handlers
import math
import os
import pathlib
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel, Field

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Internal modules
from src import (  # noqa: E402
    ai_decisions_generator,
    dashboard,
    database,
    git_integration,
    resolution_checker,
)
from src.gemini_tracker import track_gemini_call  # noqa: E402
from src.logging_config import setup_api_logging  # noqa: E402
from src.database import (  # noqa: E402
    calculate_profit_with_fees,
    log_status_change,
    process_disputed_outcomes,
)

# New Components
from src.adaptive_rate_limiter import AdaptiveRateLimiter  # noqa: E402
from src.market_queue import QueueManager  # noqa: E402
from src.health_monitor import HealthMonitor  # noqa: E402
from src.error_logger import log_api_error  # noqa: E402
from src.multi_outcome_handler import MultiOutcomeHandler  # noqa: E402
from src.config_loader import load_multi_outcome_config  # noqa: E402

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

log_dir = pathlib.Path("logs")
log_dir.mkdir(exist_ok=True)
try:
    os.chmod(log_dir, 0o755)
except Exception:
    pass

log_file = log_dir / "bot.log"

# Fix permission issues
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
            sys.exit(1)

log_handlers: List[logging.Handler] = [
    logging.StreamHandler(),
    logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
        delay=True,
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
setup_api_logging()

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# New Rate Limit & Worker Config
GEMINI_RPM_INITIAL = float(os.getenv("GEMINI_RPM_INITIAL", "4.0"))
GEMINI_RPM_MIN = float(os.getenv("GEMINI_RPM_MIN", "1.0"))
GEMINI_RPM_MAX = float(os.getenv("GEMINI_RPM_MAX", "4.0"))
MARKET_FETCH_INTERVAL_MINUTES = int(os.getenv("MARKET_FETCH_INTERVAL_MINUTES", "5"))
QUEUE_SIZE_LIMIT = int(os.getenv("QUEUE_SIZE_LIMIT", "100"))
HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "60"))
HEALTH_DASHBOARD_UPDATE_MINUTES = int(
    os.getenv("HEALTH_DASHBOARD_UPDATE_MINUTES", "15")
)
MEMORY_WARNING_MB = int(os.getenv("MEMORY_WARNING_MB", "400"))
MEMORY_CRITICAL_MB = int(os.getenv("MEMORY_CRITICAL_MB", "480"))

# API URLs
POLYMARKET_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
GRAPHQL_URL = "https://api.goldsky.com/api/public/project_clrb8pu7r0abk01w14w7o5rkl/subgraphs/polymarket-markets/latest/gn"

# Strategy Params
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "10000"))
KELLY_FRACTION = 0.25
MAX_CAPITAL_FRACTION = 0.5
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.05"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.95"))
HIGH_VOLUME_THRESHOLD = float(os.getenv("HIGH_VOLUME_THRESHOLD", "50000"))
FETCH_MARKET_LIMIT = int(os.getenv("FETCH_MARKET_LIMIT", "100"))

# Global Components
rate_limiter = AdaptiveRateLimiter(
    initial_rpm=GEMINI_RPM_INITIAL, min_rpm=GEMINI_RPM_MIN, max_rpm=GEMINI_RPM_MAX
)
queue_manager = QueueManager(db_path="data/queue.db")
health_monitor = HealthMonitor(
    memory_warning_threshold_mb=MEMORY_WARNING_MB,
    memory_critical_threshold_mb=MEMORY_CRITICAL_MB,
    export_path="HEALTH_STATUS.md",
)
multi_outcome_config = load_multi_outcome_config()
multi_outcome_handler = MultiOutcomeHandler(database.SessionLocal, multi_outcome_config)

# ============================================================================
# MODELS
# ============================================================================


class MarketData(BaseModel):
    question: str = Field(..., description="Die Marktfrage")
    description: str = Field(default="", description="Detaillierte Marktbeschreibung")
    market_slug: str = Field(..., description="Eindeutige ID des Marktes (conditionId)")
    url_slug: str = Field(..., description="URL-friendly slug")
    yes_price: float = Field(..., description="Aktueller Preis für 'Yes' (0.0-1.0)")
    volume: float = Field(..., description="Handelsvolumen in USD")
    end_date: Optional[str] = Field(None, description="Enddatum des Marktes")
    group_item_title: Optional[str] = Field(
        None, description="Label for multi-outcome variant"
    )


class AIAnalysis(BaseModel):
    estimated_probability: float = Field(..., ge=0.0, le=1.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., description="Begründung der KI")


class TradingRecommendation(BaseModel):
    action: str = Field(..., description="Empfehlung: YES, NO oder PASS")
    stake_usdc: float = Field(..., description="Empfohlener Einsatz in USDC")
    kelly_fraction: float = Field(..., description="Kelly-Fraction des Kapitals")
    expected_value: float = Field(..., description="Erwarteter Gewinn")
    market_question: str = Field(..., description="Die Marktfrage")
    ai_probability: Optional[float] = None
    confidence_score: Optional[float] = None
    ai_reasoning: Optional[str] = None
    edge: Optional[float] = None


# ============================================================================
# CORE LOGIC: API & AI
# ============================================================================


@track_gemini_call
def _execute_gemini_request(client: genai.Client, prompt: str):
    """Executes the raw Gemini API request."""
    return client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )


def _generate_gemini_response(client: genai.Client, prompt: str) -> tuple[dict, dict]:
    """Generates response without internal rate limit retry loop (handled by queue)."""
    start_time = time.time()

    try:
        response = _execute_gemini_request(client, prompt)
        logger.debug(f"🔍 Gemini Raw Response Type: {type(response)}")

        response_time_ms = int((time.time() - start_time) * 1000)

        usage_meta = {
            "prompt_token_count": getattr(
                response.usage_metadata, "prompt_token_count", 0
            ),
            "candidates_token_count": getattr(
                response.usage_metadata, "candidates_token_count", 0
            ),
            "total_token_count": getattr(
                response.usage_metadata, "total_token_count", 0
            ),
            "response_time_ms": response_time_ms,
        }

        text_response = response.text
        logger.debug(f"🔍 Gemini Raw Text (first 500 chars): {text_response[:500]}")

        if "```json" in text_response:
            text_response = text_response.split("```json")[1].split("```")[0]
        elif "```" in text_response:
            text_response = text_response.split("```")[1].split("```")[0]

        text_response = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text_response)
        try:
            parsed_data = json.loads(text_response.strip())
        except Exception:
            parsed_data = json.loads(text_response.strip(), strict=False)

        return parsed_data, usage_meta

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON Parse Error: {e.msg}")
        raise
    except Exception as e:
        logger.error(f"❌ Gemini API Error: {str(e)}")
        raise


def analyze_market_with_ai(market: MarketData) -> Optional[AIAnalysis]:
    """
    Analyzes a market using Gemini AI.
    Handles rate limiting and queue reporting explicitly.
    """
    try:
        logger.info(f"🤖 Starting AI Analysis for: {market.question[:60]}")
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Analysiere folgende Wettfrage von Polymarket und schätze die Wahrscheinlichkeit ein:
        FRAGE: {market.question}
        BESCHREIBUNG: {market.description}
        AKTUELLER MARKTPREIS (Yes): {market.yes_price:.2%}
        Nutze Google Search für Fakten.
        Output JSON: {{ "estimated_probability": 0.0-1.0, "confidence_score": 0.0-1.0, "reasoning": "..." }}
        """

        result, usage_meta = _generate_gemini_response(client, prompt)

        # Success - report to rate limiter
        rate_limiter.report_success()

        logger.info(
            f"✅ AI Analysis Success - Tokens: {usage_meta['total_token_count']}, Time: {usage_meta['response_time_ms']}ms"
        )
        return AIAnalysis(**result)

    except ClientError as exc:
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            logger.error("❌ Rate Limit Exhausted (429) - Reporting to limiter")
            rate_limiter.report_429_error()
            queue_manager.move_to_retry_queue(
                market.market_slug, "RATE_LIMIT_429", str(exc)
            )
        else:
            logger.error(f"❌ Gemini Client Error: {exc}")
            rate_limiter.report_error("CLIENT_ERROR")
            queue_manager.move_to_retry_queue(market.market_slug, "API_ERROR", str(exc))

        log_api_error(
            api_name="gemini",
            endpoint="analyze_market",
            error=exc,
            context={"market_slug": market.market_slug},
        )
        return None

    except Exception as exc:
        error_type = type(exc).__name__
        logger.error(f"❌ Unexpected Error in AI Analysis: {error_type} - {exc}")

        if "JSONDecodeError" in error_type:
            queue_manager.move_to_retry_queue(
                market.market_slug, "PARSE_ERROR", str(exc)
            )
        elif "Timeout" in str(exc) or "timeout" in str(exc).lower():
            queue_manager.move_to_retry_queue(market.market_slug, "TIMEOUT", str(exc))
        else:
            queue_manager.move_to_retry_queue(
                market.market_slug, "UNKNOWN_ERROR", str(exc)
            )

        return None


def calculate_kelly_stake(
    ai_prob: float, price: float, conf: float, capital: float
) -> TradingRecommendation:
    """Calculates optimal stake size using Kelly Criterion."""
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
    """Analyzes market and returns recommendation or rejection."""
    logger.info(
        f"📊 Analysiere: {market.question} (Vol: ${market.volume:,.0f}, Price: {market.yes_price:.2f})"
    )

    ai_analysis = analyze_market_with_ai(market)

    # If None, it means error occurred and was handled (queued for retry)
    if not ai_analysis:
        return None, None

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
# API HELPERS (Existing)
# ============================================================================


def graphql_request_with_retry(query: str, max_retries: int = 3) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            logger.debug(f"🔍 GraphQL Attempt {attempt + 1}/{max_retries}")
            response = requests.post(
                GRAPHQL_URL,
                json={"query": query},
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.error("❌ GraphQL 404 Error")
                return None
            elif response.status_code in [429, 500, 502, 503, 504]:
                wait_time = 2 ** (attempt + 1)
                logger.warning(
                    f"⚠️ GraphQL {response.status_code} - Retry in {wait_time}s"
                )
                time.sleep(wait_time)
            else:
                logger.warning(f"⚠️ GraphQL HTTP {response.status_code}")
                return None
        except Exception as exc:
            logger.error(f"❌ GraphQL Error: {exc}")
            if attempt == max_retries - 1:
                return None
    return None


def execute_batched_query(
    slugs: List[str],
    query_fragment_fn: Callable[[str], str],
    chunk_size: int = 50,
) -> Dict[str, Any]:
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
            if data and data.get("data"):
                for alias, market_data in data["data"].items():
                    if market_data:
                        original_slug = slug_map.get(alias)
                        if original_slug:
                            results[original_slug] = market_data
        except Exception as exc:
            logger.error(f"❌ Batch Query Error: {exc}")
    return results


def fetch_active_markets(limit: int = 20) -> List[MarketData]:  # noqa: C901
    try:
        logger.info("📡 Connecting to Polymarket Gamma API...")
        params = {
            "closed": "false",
            "limit": limit,
            "offset": 0,
            "order": "volume",
            "ascending": "false",
        }
        response = requests.get(POLYMARKET_GAMMA_API_URL, params=params, timeout=10)  # type: ignore
        if response.status_code != 200:
            return []

        data = response.json()
        market_data_list = data if isinstance(data, list) else data.get("data", [])
        markets = []
        rejected_buffer: List[Dict[str, Any]] = []

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

            try:
                outcome_prices_raw = market.get("outcome_prices")
                outcome_prices = []
                if outcome_prices_raw:
                    if isinstance(outcome_prices_raw, str):
                        outcome_prices = json.loads(outcome_prices_raw)
                    elif isinstance(outcome_prices_raw, list):
                        outcome_prices = outcome_prices_raw

                # Multi-outcome markets are now supported and grouped later
                yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5
            except Exception:
                yes_price = 0.5

            if not (MIN_PRICE <= yes_price <= MAX_PRICE):
                if volume < HIGH_VOLUME_THRESHOLD:
                    continue

            markets.append(
                MarketData(
                    question=market.get("question", ""),
                    description=market.get("description", ""),
                    market_slug=market.get("id", ""),
                    url_slug=market.get("slug", "") or market.get("id", ""),
                    yes_price=yes_price,
                    volume=volume,
                    end_date=end_date_str,
                    group_item_title=market.get("groupItemTitle"),
                )
            )

        if rejected_buffer:
            database.insert_rejected_markets_batch(rejected_buffer)

        return markets
    except Exception as exc:
        logger.error(f"⚠️ Market Fetch Error: {exc}")
        return []


def fetch_missing_end_dates(markets: List[MarketData]) -> List[MarketData]:
    missing = [m for m in markets if not m.end_date]
    if not missing:
        return markets

    slugs = [m.market_slug for m in missing]
    data_map = execute_batched_query(
        slugs, lambda s: f"market(id: {s}) {{ end_date_iso }}"
    )

    for m in missing:
        if m.market_slug in data_map:
            val = data_map[m.market_slug].get("end_date_iso")
            if val:
                m.end_date = val
    return markets


def calculate_quick_edge(market: MarketData) -> float:
    price_dev = abs(market.yes_price - 0.5)
    vol_score = min(market.volume / 100000.0, 1.0)

    if 0.2 <= market.yes_price <= 0.8:
        penalty = 1.0
    elif 0.1 <= market.yes_price <= 0.9:
        penalty = 0.7
    else:
        penalty = 0.3

    return (1.0 - (2 * price_dev)) * 0.4 + vol_score * 0.4 + penalty * 0.2


# ============================================================================
# RESOLUTION LOGIC (Preserved)
# ============================================================================


def check_and_resolve_bets():  # noqa: C901
    try:
        # Archive expired bets
        archived = database.archive_expired_bets()
        if archived > 0:
            logger.info(f"📦 Archived {archived} expired bet(s)")

        # ===== NEU: Resolution Check =====
        try:
            resolved = resolution_checker.check_and_resolve_bets()
            if resolved > 0:
                logger.info(f"✅ Resolved {resolved} bet(s) with outcomes from Goldsky")
        except Exception as e:
            logger.error(f"❌ Error during resolution check: {e}", exc_info=True)
        # =================================

        # Process auto-losses (30+ days)
        auto_losses = database.process_auto_loss_bets()
        if auto_losses > 0:
            logger.info(f"💀 Processed {auto_losses} auto-loss bets")

        process_disputed_outcomes()

        active_bets = database.get_active_bets()
        logger.info("🔍 Checking resolution status...")

        bets_to_check = []
        for bet in active_bets:
            # Check if expired
            end_date_val = bet.get("end_date")
            is_expired = False

            if isinstance(end_date_val, str):
                try:
                    end_date = date_parser.parse(end_date_val)
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    if end_date < datetime.now(timezone.utc):
                        is_expired = True
                except Exception:
                    pass

            if is_expired:
                bets_to_check.append(bet)

        archived_unresolved = database.get_unresolved_archived_bets()

        if bets_to_check:
            process_resolution_for_bets(bets_to_check, is_archived=False)
        if archived_unresolved:
            process_resolution_for_bets(archived_unresolved, is_archived=True)

    except Exception as exc:
        logger.error(f"❌ Resolution Check Failed: {exc}", exc_info=True)


def process_resolution_for_bets(bets: List[Dict], is_archived: bool):  # noqa: C901
    unique_slugs = list(set(b["market_slug"] for b in bets))
    resolved_markets = execute_batched_query(
        unique_slugs,
        lambda safe_id: f"market(id: {safe_id}) {{ closed resolvedBy outcomes {{ price }} }}",
    )

    bets_to_close = []
    bets_to_update = []
    bets_to_mark_disputed = []

    for bet in bets:
        market_data = resolved_markets.get(bet["market_slug"])
        resolved_by = market_data.get("resolvedBy") if market_data else None

        if market_data and resolved_by:
            if resolved_by == "ANNULLED":
                if is_archived:
                    bets_to_update.append((bet["archive_id"], "ANNULLED", 0.0))
                else:
                    bets_to_close.append((bet["bet_id"], "ANNULLED", 0.0))
                continue

            outcomes = market_data.get("outcomes", [])
            prices = (
                [float(o.get("price", 0)) for o in outcomes if o] if outcomes else []
            )
            actual_outcome = None

            if prices and len(prices) >= 2:
                p_yes = float(prices[0])
                if p_yes > 0.9:
                    actual_outcome = "YES"
                elif p_yes < 0.1:
                    actual_outcome = "NO"
                elif 0.1 <= p_yes <= 0.9:
                    # Disputed
                    if is_archived:
                        bets_to_mark_disputed.append((bet["archive_id"], p_yes))
                    else:
                        database.archive_bet_without_resolution(bet["bet_id"])
                    continue

            if actual_outcome:
                stake = float(bet["stake_usdc"])
                entry = float(bet["entry_price"])
                gas_fee = 0.50
                profit = calculate_profit_with_fees(
                    stake, entry, bet["action"], actual_outcome, gas_fee
                )

                if is_archived:
                    bets_to_update.append((bet["archive_id"], actual_outcome, profit))
                else:
                    bets_to_close.append((bet["bet_id"], actual_outcome, profit))
        else:
            # Not resolved, check if we need to archive active bet
            if not is_archived:
                database.archive_bet_without_resolution(bet["bet_id"])

    if bets_to_close:
        database.close_bets_batch(bets_to_close)
    if bets_to_update:
        database.update_archived_bets_outcome_batch(bets_to_update)
    if bets_to_mark_disputed:
        for archive_id, price in bets_to_mark_disputed:
            log_status_change(
                archive_id, "UNRESOLVED", "DISPUTED", f"PRICE_{price}", True
            )


# ============================================================================
# WORKER THREADS
# ============================================================================


def market_discovery_worker():  # noqa: C901
    """Fetches markets periodically and adds them to the queue."""
    logger.info("✅ Started thread: MarketDiscovery")

    while True:
        try:
            logger.info(
                f"🔍 Market Discovery Cycle (Every {MARKET_FETCH_INTERVAL_MINUTES} min)"
            )

            # 1. Fetch Markets
            raw_markets = fetch_active_markets(limit=FETCH_MARKET_LIMIT)

            # 2. Add End Dates
            markets = fetch_missing_end_dates(raw_markets)

            # 3. Filter Active Bets
            active_slugs = database.get_active_bet_slugs()

            # 4. Group Markets
            groups = multi_outcome_handler.group_markets(markets)

            added_count = 0

            # Process Singles
            for market in groups["single_markets"]:
                if market.market_slug in active_slugs:
                    continue

                priority = calculate_quick_edge(market)
                market_dict = market.dict()

                if queue_manager.add_market(market_dict, priority):
                    added_count += 1

            # Process Multi-Outcome
            for parent_slug, outcomes in groups["multi_outcome_events"].items():
                # Check conflicts
                conflict = multi_outcome_handler.check_existing_bets(parent_slug)
                if conflict:
                    logger.info(f"Skipping multi-outcome {parent_slug}: {conflict}")
                    continue

                # Prepare queue item
                queue_item = {
                    "market_slug": parent_slug,
                    "is_multi_outcome": True,
                    "parent_slug": parent_slug,
                    "outcomes": [m.dict() for m in outcomes],
                    "question": f"Multi-Outcome: {outcomes[0].question} ...",
                }

                # Calculate priority
                priority = max(calculate_quick_edge(m) for m in outcomes)

                if queue_manager.add_market(queue_item, priority):
                    added_count += 1

            logger.info(
                f"✅ Market Discovery: {added_count} new markets added to queue"
            )

            # 4. Check Retry Queue
            requeued = queue_manager.check_retry_queue()
            if requeued:
                logger.info(f"🔄 Requeued {len(requeued)} markets from retry queue")

            # 5. Cleanup
            queue_manager.cleanup_old_entries()

            # Sleep
            time.sleep(MARKET_FETCH_INTERVAL_MINUTES * 60)

        except Exception as e:
            logger.error(f"❌ Error in MarketDiscovery: {e}")
            time.sleep(60)


def queue_processing_worker():  # noqa: C901
    """Continuously processes the market queue."""
    logger.info("✅ Started thread: QueueProcessor")

    while True:
        try:
            # 1. Pop next market
            market_data = queue_manager.pop_next_market()

            if not market_data:
                # Queue empty, wait a bit
                time.sleep(30)
                continue

            logger.info(f"📤 Popped from queue: {market_data.get('question')[:50]}")

            # 2. Check if Multi-Outcome
            if market_data.get("is_multi_outcome"):
                parent_slug = market_data.get("parent_slug")
                outcomes = [MarketData(**m) for m in market_data.get("outcomes")]

                # Acquire Token
                logger.debug("⏳ Acquiring rate limit token for multi-outcome...")
                if not rate_limiter.acquire_token(block=True):
                    continue

                client = genai.Client(api_key=GEMINI_API_KEY)
                analysis = multi_outcome_handler.analyze_multi_outcome_event(
                    parent_slug, outcomes, client
                )

                if analysis:
                    market_map = {m.market_slug: m for m in outcomes}
                    best = multi_outcome_handler.select_best_outcome(
                        analysis, market_map
                    )

                    if best:
                        m = best["market"]
                        capital = database.get_current_capital()

                        rec = calculate_kelly_stake(
                            best["ai_probability"],
                            m.yes_price,
                            best["confidence"],
                            capital,
                        )

                        if rec.action != "PASS":
                            bet_data = {
                                "market_slug": m.market_slug,
                                "parent_event_slug": parent_slug,
                                "outcome_variant_id": m.market_slug,
                                "is_multi_outcome": True,
                                "url_slug": m.url_slug,
                                "question": m.question,
                                "action": best["action"],
                                "stake_usdc": rec.stake_usdc,
                                "entry_price": m.yes_price,
                                "ai_probability": best["ai_probability"],
                                "confidence_score": best["confidence"],
                                "expected_value": rec.expected_value,
                                "edge": best["edge"],
                                "ai_reasoning": best["reasoning"],
                                "end_date": m.end_date,
                            }
                            database.insert_active_bets_batch([bet_data])
                            queue_manager.mark_completed(
                                parent_slug,
                                f"BET: {rec.action} on {m.market_slug} (${rec.stake_usdc})",
                            )
                        else:
                            queue_manager.mark_completed(
                                parent_slug, "PASS: Kelly too low or Edge too small"
                            )
                    else:
                        queue_manager.mark_completed(
                            parent_slug, "PASS: No profitable outcome found"
                        )
                else:
                    # Analysis failed
                    queue_manager.move_to_retry_queue(
                        parent_slug, "ANALYSIS_FAILED", "Null response"
                    )

            else:
                # Single Market Logic
                market = MarketData(**market_data)

                # 3. Acquire Token (Blocks)
                logger.debug("⏳ Acquiring rate limit token...")
                if not rate_limiter.acquire_token(block=True):
                    continue

                # 4. Analyze
                capital = database.get_current_capital()
                rec, rejection = analyze_and_recommend(market, capital)

                # 5. Process Result
                if rejection:
                    database.insert_rejected_markets_batch([rejection])
                    queue_manager.mark_completed(
                        market.market_slug, f"REJECTED: {rejection['rejection_reason']}"
                    )

                elif rec:
                    if rec.action != "PASS":
                        bet_data = {
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
                        database.insert_active_bets_batch([bet_data])
                        queue_manager.mark_completed(
                            market.market_slug, f"BET: {rec.action} ${rec.stake_usdc}"
                        )
                    else:
                        queue_manager.mark_completed(market.market_slug, "PASS")
                else:
                    pass

        except Exception as e:
            logger.error(f"❌ Error in QueueProcessor: {e}")
            time.sleep(10)


def health_monitoring_worker():
    """Monitors system health and updates dashboard."""
    logger.info("✅ Started thread: HealthMonitor")

    last_dashboard_update = 0

    while True:
        try:
            # Collect Metrics
            api_stats = rate_limiter.get_stats()
            queue_stats = queue_manager.get_queue_stats()

            metrics = health_monitor.collect_metrics(api_stats, queue_stats)
            health_monitor.log_heartbeat(metrics)

            # Export Dashboard
            now = time.time()
            if now - last_dashboard_update > (HEALTH_DASHBOARD_UPDATE_MINUTES * 60):
                health_monitor.export_health_dashboard(metrics)

                # Update other dashboards
                try:
                    dashboard.generate_dashboard()
                    ai_decisions_generator.generate_ai_decisions_file()
                    git_integration.push_dashboard_update()
                    logger.info("📊 Dashboards updated and pushed")
                except Exception as e:
                    logger.error(f"❌ Failed to update dashboards: {e}")

                last_dashboard_update = now

            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f"❌ Error in HealthMonitor: {e}")
            time.sleep(60)


def resolution_worker():
    """Periodically resolves bets."""
    logger.info("✅ Started thread: ResolutionWorker")

    while True:
        try:
            check_and_resolve_bets()
            time.sleep(900)  # 15 minutes
        except Exception as e:
            logger.error(f"❌ Error in ResolutionWorker: {e}")
            time.sleep(60)


# ============================================================================
# MAIN LOOP
# ============================================================================


def main_loop():
    if not GEMINI_API_KEY:
        logger.error("❌ GEMINI_API_KEY not set!")
        sys.exit(1)

    database.init_database()
    logger.info("🚀 Polymarket Bot - Continuous Processing System v2.0 Starting...")
    logger.info(f"⚙️ Config: RPM={GEMINI_RPM_INITIAL}, QueueLimit={QUEUE_SIZE_LIMIT}")

    # Create Threads
    threads = [
        threading.Thread(target=market_discovery_worker, daemon=True),
        threading.Thread(target=queue_processing_worker, daemon=True),
        threading.Thread(target=health_monitoring_worker, daemon=True),
        threading.Thread(target=resolution_worker, daemon=True),
    ]

    # Start Threads
    for t in threads:
        t.start()

    logger.info("✅ All workers started. Entering main loop...")

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown requested. Exiting...")
        sys.exit(0)


if __name__ == "__main__":
    main_loop()
