import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Constants
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"


class ClobClient:
    """
    Client for interacting with Polymarket's CLOB API.
    Handles both Real Trading (if keys and library present) and Simulation.
    """

    def __init__(self, host: str = CLOB_API_URL, chain_id: int = 137):
        self.host = host
        self.chain_id = chain_id
        self.client = None
        self.simulation_mode = True

        # Try to initialize real client
        self.api_key = os.getenv("POLYMARKET_API_KEY")
        self.secret = os.getenv("POLYMARKET_SECRET")
        self.passphrase = os.getenv("POLYMARKET_PASSPHRASE")
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        self.proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")

        try:
            from py_clob_client.client import ClobClient as PyClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Re-export constants for external use
            self.OrderArgs = OrderArgs
            self.OrderType = OrderType
            self.BUY = BUY
            self.SELL = SELL

            if self.private_key and self.proxy_address:
                logger.info("🔐 Initializing Real CLOB Client...")
                self.client = PyClobClient(
                    host,
                    key=self.private_key,
                    chain_id=chain_id,
                    signature_type=2,  # 1=Email, 2=Browser/Proxy
                    funder=self.proxy_address,
                )
                self.client.set_api_creds(self.client.create_or_derive_api_creds())
                self.simulation_mode = False
                logger.info("✅ Real CLOB Client Initialized.")
            else:
                logger.warning(
                    "⚠️ Missing Private Key or Proxy Address. Running in SIMULATION MODE."
                )

        except ImportError:
            logger.warning(
                "⚠️ py-clob-client not installed. Running in SIMULATION MODE."
            )
            # Define Mock constants

            class MockConstants:
                GTC = "GTC"
                FOK = "FOK"
                GTD = "GTD"

            self.OrderType = MockConstants()
            self.BUY = "BUY"
            self.SELL = "SELL"
            self.OrderArgs = dict

    def get_market(self, condition_id: str) -> Optional[Dict]:
        """Fetches market details from Gamma API (Public)."""
        try:
            url = f"{GAMMA_API_URL}/{condition_id}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"⚠️ Market not found: {condition_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching market {condition_id}: {e}")
            return None

    def get_orderbook(self, token_id: str) -> Dict[str, List]:
        """
        Fetches the orderbook directly from CLOB API (Public).
        Bypasses Gamma API delay.
        """
        try:
            url = f"{self.host}/book"
            params = {"token_id": token_id}
            resp = requests.get(url, params=params, timeout=5)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                return {"bids": [], "asks": []}
            else:
                logger.warning(f"⚠️ Failed to fetch orderbook: {resp.status_code}")
                return {"bids": [], "asks": []}

        except Exception as e:
            logger.error(f"❌ Error fetching orderbook for {token_id}: {e}")
            return {"bids": [], "asks": []}

    def get_mid_price(self, token_id: str) -> Optional[float]:
        """Calculates mid price from orderbook."""
        ob = self.get_orderbook(token_id)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])

        return (best_bid + best_ask) / 2.0

    def create_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str,
    ) -> Any:
        """Creates a signed order object."""
        if self.simulation_mode or not self.client:
            return {
                "token_id": token_id,
                "price": price,
                "size": size,
                "side": side,
                "mock_signature": "0x123...",
            }

        return self.client.create_order(
            self.OrderArgs(
                price=price,
                size=size,
                side=side,
                token_id=token_id,
            )
        )

    def post_order(
        self,
        order: Any,
        order_type: str = "GTC",
        post_only: bool = False,
    ) -> Dict:
        """Posts the order to the CLOB."""
        if self.simulation_mode or not self.client:
            logger.info(
                f"🧪 [SIMULATION] Posting Order: {order.get('side')} {order.get('size')} @ {order.get('price')} "
                f"(Type: {order_type}, PostOnly: {post_only})"
            )
            time.sleep(0.5)  # Simulate network delay
            return {
                "success": True,
                "orderID": f"mock_order_{int(time.time())}",
                "status": "live" if post_only else "matched",
            }

        try:
            # Try passing post_only as a kwarg if the library supports it
            # Some versions might expect it in the payload, others as a param
            # We attempt to pass it to post_order
            return self.client.post_order(order, order_type, postOnly=post_only)
        except TypeError:
            # Fallback: Library might not accept kwargs or expects it differently
            logger.warning("⚠️ Library rejected postOnly kwarg. Sending without.")
            try:
                return self.client.post_order(order, order_type)
            except Exception as e:
                logger.error(f"❌ Error posting order (fallback): {e}")
                return {"success": False, "errorMsg": str(e)}
        except Exception as e:
            logger.error(f"❌ Error posting order: {e}")
            return {"success": False, "errorMsg": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """Cancels an order."""
        if self.simulation_mode or not self.client:
            logger.info(f"🧪 [SIMULATION] Cancelling Order: {order_id}")
            return True

        try:
            self.client.cancel(order_id)
            return True
        except Exception as e:
            logger.error(f"❌ Error cancelling order: {e}")
            return False

    def cancel_all(self):
        """Cancels all open orders."""
        if self.simulation_mode or not self.client:
            logger.info("🧪 [SIMULATION] Cancelling ALL Orders")
            return True
        try:
            self.client.cancel_all()
            return True
        except Exception as e:
            logger.error(f"❌ Error cancelling all orders: {e}")
            return False
