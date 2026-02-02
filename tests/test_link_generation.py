import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import requests
from src.dashboard import to_cet

# Mocking the module since I haven't implemented it in src/ai_decisions_generator.py yet
# I will define the function here for testing, then copy it to the source file
# Or I can assume I will modify the source file first?
# The plan says "Create Test" first. So I will put the test logic here.

def get_polymarket_url(slug, session=None):
    if not slug:
        return "https://polymarket.com"

    formats = [
        f"https://polymarket.com/event/{slug}",
        f"https://polymarket.com/market/{slug}"
    ]

    # If no session provided, create a temporary one (but better to reuse)
    local_session = session or requests.Session()

    # Try /event/ first
    try:
        resp = local_session.head(formats[0], timeout=2, allow_redirects=True)
        if resp.status_code == 200:
            return formats[0]
    except Exception:
        pass

    # Try /market/ second
    try:
        resp = local_session.head(formats[1], timeout=2, allow_redirects=True)
        if resp.status_code == 200:
            return formats[1]
    except Exception:
        pass

    # Fallback
    return formats[0]

class TestLinkGeneration(unittest.TestCase):
    def test_get_polymarket_url_event_success(self):
        with patch('requests.Session') as MockSession:
            session = MockSession()
            # First call returns 200
            session.head.return_value.status_code = 200

            url = get_polymarket_url("test-slug", session)
            self.assertEqual(url, "https://polymarket.com/event/test-slug")
            session.head.assert_called_with("https://polymarket.com/event/test-slug", timeout=2, allow_redirects=True)

    def test_get_polymarket_url_market_fallback(self):
        with patch('requests.Session') as MockSession:
            session = MockSession()
            # First call returns 404, second returns 200
            mock_resp_404 = MagicMock()
            mock_resp_404.status_code = 404
            mock_resp_200 = MagicMock()
            mock_resp_200.status_code = 200

            session.head.side_effect = [mock_resp_404, mock_resp_200]

            url = get_polymarket_url("test-slug", session)
            self.assertEqual(url, "https://polymarket.com/market/test-slug")

    def test_get_polymarket_url_failure_fallback(self):
        with patch('requests.Session') as MockSession:
            session = MockSession()
            # Both fail
            session.head.side_effect = Exception("Connection Error")

            url = get_polymarket_url("test-slug", session)
            self.assertEqual(url, "https://polymarket.com/event/test-slug")

    def test_to_cet_conversion(self):
        # Test basic conversion
        dt_utc = datetime(2023, 1, 1, 12, 0) # Naive, assumed UTC if logic handles it, or explicit
        # The to_cet implementation handles naive as UTC
        cet_dt = to_cet(dt_utc)
        self.assertIsNotNone(cet_dt)
        # CET is UTC+1 in winter
        self.assertEqual(cet_dt.hour, 13)
