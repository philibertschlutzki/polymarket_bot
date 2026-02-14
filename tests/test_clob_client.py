import unittest
from unittest.mock import MagicMock, patch

from src.clob_client import ClobClient


class TestClobClient(unittest.TestCase):
    def setUp(self):
        self.client = ClobClient()

    def test_simulation_mode_default(self):
        """Test that client defaults to simulation mode if no keys."""
        # Ensure env vars are not set (mock them if needed, but locally they might be missing)
        with patch.dict("os.environ", {}, clear=True):
            client = ClobClient()
            self.assertTrue(client.simulation_mode)
            self.assertIsNone(client.client)

    @patch("src.clob_client.requests.get")
    def test_get_orderbook(self, mock_get):
        """Test get_orderbook calls the correct URL."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"bids": [], "asks": []}
        mock_get.return_value = mock_resp

        ob = self.client.get_orderbook("123")
        self.assertEqual(ob, {"bids": [], "asks": []})
        mock_get.assert_called_with(
            "https://clob.polymarket.com/book", params={"token_id": "123"}, timeout=5
        )

    def test_post_order_simulation(self):
        """Test post_order returns mock response in simulation."""
        self.client.simulation_mode = True
        resp = self.client.post_order(
            {"token_id": "123"}, order_type=self.client.OrderType.GTC
        )
        self.assertTrue(resp["success"])
        self.assertTrue("mock_order" in resp["orderID"])

    def test_create_order_simulation(self):
        """Test create_order returns mock object."""
        self.client.simulation_mode = True
        order = self.client.create_order("123", 0.5, 10, "BUY")
        self.assertEqual(order["token_id"], "123")
        self.assertEqual(order["mock_signature"], "0x123...")


if __name__ == "__main__":
    unittest.main()
