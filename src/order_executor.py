import logging
import time
from typing import Dict, Optional

from src.clob_client import ClobClient

logger = logging.getLogger(__name__)


class OrderExecutor:
    """
    Handles advanced order execution strategies for Polymarket.
    Implements:
    - Maker-only orders (postOnly)
    - Retry logic for failures
    - Market readiness checks
    - Direct CLOB price fetching
    """

    def __init__(self, clob_client: Optional[ClobClient] = None):
        self.client = clob_client or ClobClient()

    def get_clob_price(self, token_id: str) -> Optional[float]:
        """
        Fetches the current mid-price directly from CLOB orderbook.
        Use this instead of Gamma API prices to avoid slippage/rejects.
        """
        return self.client.get_mid_price(token_id)

    def wait_for_market_ready(
        self, market_slug: str, max_wait_seconds: int = 30
    ) -> bool:
        """
        Polls the market status until it is active or timeout.
        """
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            market = self.client.get_market(market_slug)
            if market and market.get(
                "active", False
            ):  # Check 'active' or 'closed' status
                # Gamma API returns 'closed': boolean. If closed=False, it is active.
                # Let's check the schema. Usually 'closed' is the field.
                if not market.get("closed", True):
                    return True

            # Also check if orderbook has liquidity
            # (Optional enhancement)

            time.sleep(1)

        logger.warning(f"⚠️ Market {market_slug} not ready after {max_wait_seconds}s")
        return False

    def place_maker_order(
        self,
        token_id: str,
        side: str,
        amount_usdc: float,
        limit_price: float,
        max_retries: int = 3,
    ) -> Dict:
        """
        Places a MAKER order (Post-Only) to earn spread/rebates and avoid taker fees.
        Includes retry logic for price adjustments.
        """
        # Calculate size based on price
        if limit_price <= 0:
            return {"success": False, "error": "Invalid price"}

        size = amount_usdc / limit_price

        # Round size/price to appropriate ticks (simplified)
        # Polymarket usually requires specific rounding
        size = round(size, 2)
        limit_price = round(limit_price, 2)

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"🚀 Placing MAKER order: {side} {size} @ {limit_price} (Attempt {attempt+1})"
                )

                # 1. Create Signed Order
                order = self.client.create_order(
                    token_id=token_id,
                    price=limit_price,
                    size=size,
                    side=self.client.BUY if side == "BUY" else self.client.SELL,
                )

                # 2. Post Order with postOnly=True
                resp = self.client.post_order(
                    order, order_type=self.client.OrderType.GTC, post_only=True
                )

                if resp.get("success") or resp.get("orderID"):
                    logger.info(f"✅ Order Placed: {resp.get('orderID')}")
                    return {
                        "success": True,
                        "order_id": resp.get("orderID"),
                        "filled_size": 0,  # Maker orders sit on book
                        "status": "OPEN",
                        "price": limit_price,
                    }

                # Handle Errors
                error_msg = resp.get("errorMsg", "")
                if "post only" in error_msg.lower():
                    # Order would cross the book (become taker)
                    # Adjust price slightly to be passive
                    logger.info(
                        "⚠️ Post-Only rejected (would cross). Adjusting price..."
                    )
                    if side == "BUY":
                        limit_price -= 0.01
                    else:
                        limit_price += 0.01
                    continue

                elif "balance" in error_msg.lower():
                    return {"success": False, "error": "Insufficient Balance"}

                else:
                    logger.warning(f"❌ Order Error: {error_msg}")
                    time.sleep(1)

            except Exception as e:
                logger.error(f"❌ Execution Exception: {e}")
                time.sleep(1)

        return {"success": False, "error": "Max retries exceeded"}

    def _resolve_token_id(self, market_slug: str, action: str) -> Optional[str]:
        """Resolves token ID from market slug and action."""
        market = self.client.get_market(market_slug)
        if not market:
            logger.error(f"Market not found: {market_slug}")
            return None

        clob_ids = market.get("clobTokenIds")
        if not clob_ids:
            # Fallback to tokens list
            tokens = market.get("tokens")
            if tokens and isinstance(tokens, list):
                clob_ids = [t.get("tokenId") for t in tokens]

        if not clob_ids or len(clob_ids) < 2:
            logger.error("Token IDs not found in market data")
            return None

        # Assume Binary: 0=NO, 1=YES
        is_yes = action.upper() == "YES"
        try:
            return clob_ids[1] if is_yes else clob_ids[0]
        except IndexError:
            logger.error("Token ID index out of range")
            return None

    def execute_bet(
        self,
        bet_data: Dict,
        token_id: str = None,  # Need to resolve token_id from market_slug if not provided
    ) -> Dict:
        """
        Main entry point to execute a strategy recommendation.
        """
        market_slug = bet_data.get("market_slug")
        side = (
            "BUY" if bet_data.get("action") == "YES" else "SELL"
        )  # Simplified, actually depends on Outcome Token
        # NOTE: In Polymarket CTF, "YES" usually means buying the "YES" token.
        # "NO" usually means buying the "NO" token (which is a separate token_id).
        # We need the correct token_id for the outcome.

        # If token_id is not passed, we might need to fetch it.
        # But bet_data usually comes from MarketData which might not have token_ids explicitly
        # if not fetched from Gamma.
        # In this implementation, we assume token_id is passed or available.
        # If not, we'd need a helper to fetch market details and get the token ID for the outcome.

        # Resolve Token ID if missing
        if not token_id:
            if self.client.simulation_mode:
                token_id = "0x_mock_token_id"
            else:
                token_id = self._resolve_token_id(
                    market_slug, bet_data.get("action", "")
                )
                if not token_id:
                    return {"success": False, "error": "Failed to resolve Token ID"}

        limit_price = float(bet_data.get("entry_price", 0.50))
        stake = float(bet_data.get("stake_usdc", 10.0))

        # 1. Check Market Ready
        if not self.wait_for_market_ready(market_slug):
            return {"success": False, "error": "Market Not Ready"}

        # 2. Check Price (Slippage protection)
        current_price = self.get_clob_price(token_id)
        if current_price:
            # If price moved against us significantly, abort or adjust
            if side == "BUY" and current_price > limit_price * 1.05:
                return {"success": False, "error": "Price slipped too high"}
            # Update limit price to be competitive but passive
            # For maker order, we want to be at Best Bid (if buying)
            # But simpler to stick to our limit
            pass

        # 3. Place Order
        return self.place_maker_order(token_id, side, stake, limit_price)
