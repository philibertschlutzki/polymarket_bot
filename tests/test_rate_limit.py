
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import sys
import os
import logging
import requests

# Ensure src is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import RateLimiter, retry_with_rate_limit_handling
from google.genai.errors import ClientError

# Setup logging to avoid polluting output
logging.basicConfig(level=logging.CRITICAL)

class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        self.limiter = RateLimiter(max_requests_per_minute=2)

    @patch('src.main.time.sleep')
    def test_rate_limiter_window(self, mock_sleep):
        """Test that rate limiter allows requests within limit"""
        self.limiter.wait_if_needed() # 1st request
        self.assertEqual(len(self.limiter.requests), 1)
        mock_sleep.assert_not_called()

        self.limiter.wait_if_needed() # 2nd request
        self.assertEqual(len(self.limiter.requests), 2)
        mock_sleep.assert_not_called()

    @patch('src.main.time.sleep')
    @patch('src.main.datetime')
    def test_rate_limiter_blocks(self, mock_datetime, mock_sleep):
        """Test that rate limiter blocks when limit reached"""
        # Mock datetime.now() to return fixed times
        base_time = datetime(2023, 1, 1, 12, 0, 0)

        self.limiter.requests = [
            base_time,
            base_time + timedelta(seconds=1)
        ]

        # Now is 30 seconds later
        mock_datetime.now.return_value = base_time + timedelta(seconds=30)

        self.limiter.wait_if_needed()

        # Should have slept: 60 - (30 - 0) = 30 seconds
        # logic: elapsed = (now - oldest).total_seconds() => 30. sleep = 60 - 30 = 30.
        # Plus 1s buffer = 31s

        mock_sleep.assert_called_with(31.0)
        self.assertEqual(len(self.limiter.requests), 3)

    @patch('src.main.time.sleep')
    def test_extended_backoff(self, mock_sleep):
        """Test extended backoff functionality"""
        self.limiter.set_extended_backoff(10)
        self.assertIsNotNone(self.limiter.backoff_until)

        # Next call should sleep
        self.limiter.wait_if_needed()
        mock_sleep.assert_called()
        self.assertIsNone(self.limiter.backoff_until)

class TestRetryDecorator(unittest.TestCase):

    def _create_429_error(self):
        mock_response = requests.Response()
        mock_response.status_code = 429
        mock_response.reason = "RESOURCE_EXHAUSTED"
        mock_response._content = b'{"message": "Resource exhausted"}'
        return ClientError(429, response=mock_response)

    @patch('src.main.time.sleep')
    def test_retry_on_429(self, mock_sleep):
        """Test retry logic for 429 errors"""

        mock_func = MagicMock()
        # Side effect: raise 429 twice, then succeed
        error_429 = self._create_429_error()
        mock_func.side_effect = [error_429, error_429, "Success"]

        decorated = retry_with_rate_limit_handling(mock_func)
        result = decorated("arg")

        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 3)

        # Should have slept twice.
        # Attempt 0 fails -> sleep 60*(0+1) = 60
        # Attempt 1 fails -> sleep 60*(1+1) = 120
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(60)
        mock_sleep.assert_any_call(120)

    @patch('src.main.time.sleep')
    def test_retry_exhausted_429(self, mock_sleep):
        """Test retry exhaustion for 429 errors"""
        mock_func = MagicMock()
        error_429 = self._create_429_error()
        mock_func.side_effect = error_429

        decorated = retry_with_rate_limit_handling(mock_func)

        with self.assertRaises(ClientError):
            decorated()

        self.assertEqual(mock_func.call_count, 3) # Max attempts is 3

    @patch('src.main.time.sleep')
    def test_other_exceptions(self, mock_sleep):
        """Test normal backoff for other exceptions"""
        mock_func = MagicMock()
        mock_func.side_effect = [Exception("Random error"), "Success"]

        decorated = retry_with_rate_limit_handling(mock_func)
        result = decorated()

        self.assertEqual(result, "Success")
        # Should use exponential backoff: 2**(0+2) = 4
        mock_sleep.assert_called_with(4)

if __name__ == '__main__':
    unittest.main()
