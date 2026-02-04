"""
Resolution Checker Module for Polymarket Bot
Checks Goldsky GraphQL API for market resolutions and updates archived bets.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

from src import database

logger = logging.getLogger(__name__)

# Constants
GOLDSKY_URL = "https://api.goldsky.com/api/public/project_clrb8pu7r0abk01w14w7o5rkl/subgraphs/polymarket-markets/latest/gn"
BATCH_SIZE = 50  # Max markets per GraphQL query
MIN_HOURS_AFTER_END = 1  # Wait 1h after end_date before checking
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30


def check_and_resolve_bets() -> int:
    """
    Main function: Checks unresolved bets and updates with outcomes from Goldsky.

    Returns:
        Number of bets resolved
    """
    logger.info("🔍 Starting resolution check...")

    # Get unresolved bets that are at least 1h past end_date
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=MIN_HOURS_AFTER_END)
    unresolved_bets = database.get_unresolved_archived_bets()

    # Filter: only check bets past cutoff
    eligible_bets = [
        b for b in unresolved_bets
        if b.get("end_date") and
        _parse_datetime(b["end_date"]) < cutoff_time
    ]

    if not eligible_bets:
        logger.info("✅ No bets eligible for resolution check")
        return 0

    logger.info(f"📋 Found {len(eligible_bets)} bets to check")

    # Batch process
    resolved_count = 0
    for i in range(0, len(eligible_bets), BATCH_SIZE):
        batch = eligible_bets[i:i + BATCH_SIZE]
        resolved_count += _process_batch(batch)

    logger.info(f"✅ Resolution check complete. Resolved: {resolved_count}/{len(eligible_bets)}")
    return resolved_count


def _process_batch(bets: List[Dict]) -> int:
    """Process a batch of bets for resolution."""
    market_ids = [b["market_slug"] for b in bets]
    bet_map = {b["market_slug"]: b for b in bets}

    # Query Goldsky
    market_data = _query_goldsky(market_ids)
    if not market_data:
        logger.warning("⚠️ Goldsky query returned no data")
        return 0

    # Process results
    resolutions = []
    for market in market_data:
        market_id = market["id"]
        bet = bet_map.get(market_id)
        if not bet:
            continue

        outcome, profit_loss = _determine_outcome(market, bet)
        if outcome:
            resolutions.append((bet["archive_id"], outcome, profit_loss))

    # Batch update database
    if resolutions:
        database.update_archived_bets_outcome_batch(resolutions)
        logger.info(f"✅ Batch resolved {len(resolutions)} bets")

    return len(resolutions)


def _query_goldsky(market_ids: List[str]) -> Optional[List[Dict]]:
    """
    Query Goldsky GraphQL API for market resolutions.

    Args:
        market_ids: List of market IDs (slugs)

    Returns:
        List of market data or None if error
    """
    query = """
    query GetMarketResolutions($ids: [ID!]!) {
      markets(where: { id_in: $ids }) {
        id
        closed
        resolvedBy
        outcomes {
          id
          price
        }
        end_date_iso
      }
    }
    """

    variables = {"ids": market_ids}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                GOLDSKY_URL,
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()

            data = response.json()
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                return None

            return data.get("data", {}).get("markets", [])

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Goldsky request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("❌ Goldsky query failed after max retries")
                return None

    return None


def _determine_outcome(market: Dict, bet: Dict) -> Tuple[Optional[str], float]:
    """
    Determines outcome and profit/loss from Goldsky market data.

    Args:
        market: Goldsky market data
        bet: Archived bet record

    Returns:
        (outcome, profit_loss) or (None, 0.0) if not resolved
    """
    # Check if market is resolved
    if not market.get("closed") or not market.get("resolvedBy"):
        return None, 0.0

    # Get YES outcome price (outcomes is typically YES)
    outcomes = market.get("outcomes", [])
    if not outcomes:
        logger.warning(f"No outcomes found for market {market['id']}")
        return None, 0.0

    # Assume first outcome is YES (standard for binary markets)
    yes_price_str = outcomes[0].get("price", "0.5")
    try:
        yes_price = float(yes_price_str)
    except ValueError:
        logger.error(f"Invalid price format for {market['id']}: {yes_price_str}")
        return None, 0.0

    # Determine outcome
    if yes_price >= 0.95:
        actual_outcome = "YES"
    elif yes_price <= 0.05:
        actual_outcome = "NO"
    elif 0.1 <= yes_price <= 0.9:
        actual_outcome = "DISPUTED"
        # Disputed bets are handled by process_disputed_outcomes() after 7 days
        profit_loss = 0.0  # No immediate P/L change
        return actual_outcome, profit_loss
    else:
        # Edge case: unclear price (0.05-0.1 or 0.9-0.95)
        logger.warning(f"Unclear resolution price {yes_price} for {market['id']}, marking as DISPUTED")
        return "DISPUTED", 0.0

    # Calculate profit/loss
    stake = float(bet["stake_usdc"])
    entry_price = float(bet["entry_price"])
    action = bet["action"]

    profit_loss = database.calculate_profit_with_fees(
        stake=stake,
        entry_price=entry_price,
        action=action,
        actual_outcome=actual_outcome,
        gas_fee=0.50
    )

    return actual_outcome, profit_loss


def _parse_datetime(dt_value) -> datetime:
    """Parse datetime from string or datetime object."""
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value

    if isinstance(dt_value, str):
        from dateutil import parser
        dt = parser.parse(dt_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    raise ValueError(f"Cannot parse datetime: {dt_value}")


# Standalone execution for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    count = check_and_resolve_bets()
    print(f"Resolved {count} bets")
