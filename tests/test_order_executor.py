import unittest
from unittest.mock import MagicMock, patch

from src.order_executor import OrderExecutor


class TestOrderExecutor(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.executor = OrderExecutor(clob_client=self.mock_client)
        # Setup mock client constants
        self.mock_client.BUY = "BUY"
        self.mock_client.SELL = "SELL"
        self.mock_client.OrderType.GTC = "GTC"

    def test_place_maker_order_success(self):
        """Test successful maker order placement."""
        self.mock_client.post_order.return_value = {"success": True, "orderID": "0x123"}
        self.mock_client.create_order.return_value = {"signed": "order"}

        res = self.executor.place_maker_order("token1", "BUY", 100, 0.5)

        self.assertTrue(res["success"])
        self.assertEqual(res["order_id"], "0x123")
        self.mock_client.post_order.assert_called_with(
            {"signed": "order"}, order_type="GTC", post_only=True
        )

    def test_place_maker_order_retry_on_post_only_fail(self):
        """Test retry logic when post-only fails (crosses book)."""
        # First attempt fails with post-only error, second succeeds
        self.mock_client.post_order.side_effect = [
            {"success": False, "errorMsg": "Invalid post-only order"},
            {"success": True, "orderID": "0x456"},
        ]
        self.mock_client.create_order.return_value = {"signed": "order"}

        res = self.executor.place_maker_order("token1", "BUY", 100, 0.5)

        self.assertTrue(res["success"])
        self.assertEqual(res["order_id"], "0x456")
        self.assertEqual(self.mock_client.post_order.call_count, 2)

    def test_wait_for_market_ready_timeout(self):
        """Test wait_for_market_ready times out."""
        self.mock_client.get_market.return_value = {"active": False}

        with patch("time.sleep", return_value=None): # Speed up test
            ready = self.executor.wait_for_market_ready("slug", max_wait_seconds=2)

        self.assertFalse(ready)

    def test_execute_bet_flow(self):
        """Test the full execute_bet flow."""
        self.executor.wait_for_market_ready = MagicMock(return_value=True)
        self.executor.get_clob_price = MagicMock(return_value=0.50)
        self.executor.place_maker_order = MagicMock(return_value={"success": True, "order_id": "0x999"})

        bet_data = {
            "market_slug": "test-market",
            "action": "YES",
            "entry_price": 0.50,
            "stake_usdc": 10.0
        }

        res = self.executor.execute_bet(bet_data, token_id="t1")

        self.assertTrue(res["success"])
        self.executor.wait_for_market_ready.assert_called()
        self.executor.place_maker_order.assert_called_with("t1", "BUY", 10.0, 0.50)

    def test_execute_bet_resolves_token_id(self):
        """Test execute_bet fetches token_id if missing."""
        self.executor.wait_for_market_ready = MagicMock(return_value=True)
        self.executor.place_maker_order = MagicMock(return_value={"success": True})
        self.executor.get_clob_price = MagicMock(return_value=0.50) # Fix: Return float

        # Mock client to return market with tokens
        self.mock_client.simulation_mode = False
        self.mock_client.get_market.return_value = {
            "clobTokenIds": ["token_no", "token_yes"]
        }

        bet_data = {
            "market_slug": "slug",
            "action": "YES",
            "stake_usdc": 10,
            "entry_price": 0.5
        }

        self.executor.execute_bet(bet_data) # No token_id passed

        self.mock_client.get_market.assert_called_with("slug")
        self.executor.place_maker_order.assert_called_with("token_yes", "BUY", 10, 0.5)


if __name__ == "__main__":
    unittest.main()
