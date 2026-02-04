import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import requests

from src.ai_decisions_generator import _url_cache, get_polymarket_url
from src.dashboard import to_cet


class TestLinkGeneration(unittest.TestCase):
    def setUp(self):
        # Clear cache before each test to ensure isolation
        _url_cache.clear()

    def test_get_polymarket_url_event_success(self):
        with patch("requests.Session") as MockSession:
            session = MockSession()
            # First call returns 200
            session.head.return_value.status_code = 200

            url = get_polymarket_url("slug-1", session)
            self.assertEqual(url, "https://polymarket.com/event/slug-1")
            session.head.assert_called_with(
                "https://polymarket.com/event/slug-1", timeout=2, allow_redirects=True
            )

    def test_get_polymarket_url_market_fallback(self):
        with patch("requests.Session") as MockSession:
            session = MockSession()
            # First call returns 404, second returns 200
            mock_resp_404 = MagicMock()
            mock_resp_404.status_code = 404
            mock_resp_200 = MagicMock()
            mock_resp_200.status_code = 200

            session.head.side_effect = [mock_resp_404, mock_resp_200]

            url = get_polymarket_url("slug-2", session)
            self.assertEqual(url, "https://polymarket.com/market/slug-2")

    def test_get_polymarket_url_failure_fallback(self):
        with patch("requests.Session") as MockSession:
            session = MockSession()
            # Both fail
            session.head.side_effect = Exception("Connection Error")

            url = get_polymarket_url("slug-3", session)
            self.assertEqual(url, "https://polymarket.com/event/slug-3")

    def test_to_cet_conversion(self):
        # Test basic conversion
        dt_utc = datetime(
            2023, 1, 1, 12, 0
        )  # Naive, assumed UTC if logic handles it, or explicit
        # The to_cet implementation handles naive as UTC
        cet_dt = to_cet(dt_utc)
        self.assertIsNotNone(cet_dt)
        # CET is UTC+1 in winter
        self.assertEqual(cet_dt.hour, 13)
