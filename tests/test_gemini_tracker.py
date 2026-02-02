import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gemini_tracker import GeminiRateLimitError, track_gemini_call  # noqa: E402


class TestGeminiTracker(unittest.TestCase):

    def setUp(self):
        # Reset rate limits mock before each test if needed
        pass

    @patch("src.gemini_tracker.database")
    def test_single_api_call_tracking(self, mock_db):
        # Setup mock DB
        mock_db.get_api_usage_rpm.return_value = 0
        mock_db.get_api_usage_rpd.return_value = 0
        mock_db.get_api_usage_tpm.return_value = 0

        # Mock response object
        mock_response = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 20

        @track_gemini_call
        def mock_api_call():
            return mock_response

        # Execute
        result = mock_api_call()

        # Verify
        self.assertEqual(result, mock_response)
        mock_db.log_api_usage.assert_called_once()
        args, kwargs = mock_db.log_api_usage.call_args
        self.assertEqual(kwargs["api_name"], "gemini")
        self.assertEqual(kwargs["endpoint"], "mock_api_call")
        self.assertEqual(kwargs["tokens_prompt"], 10)
        self.assertEqual(kwargs["tokens_response"], 20)

    @patch("src.gemini_tracker.database")
    @patch("src.gemini_tracker.time.sleep")
    def test_rpm_limit_enforcement(self, mock_sleep, mock_db):
        # Setup mock DB to simulate limit reached
        mock_db.get_api_usage_rpm.return_value = 15  # GEMINI_RPM_LIMIT
        mock_db.get_api_usage_rpd.return_value = 0
        mock_db.get_api_usage_tpm.return_value = 0

        mock_response = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 5

        @track_gemini_call
        def mock_api_call():
            return mock_response

        # Execute
        mock_api_call()

        # Verify sleep was called
        mock_sleep.assert_called_with(60)

    @patch("src.gemini_tracker.database")
    def test_rpd_limit_error(self, mock_db):
        # Setup mock DB to simulate daily limit reached
        mock_db.get_api_usage_rpm.return_value = 0
        mock_db.get_api_usage_rpd.return_value = 1500  # GEMINI_RPD_LIMIT
        mock_db.get_api_usage_tpm.return_value = 0

        @track_gemini_call
        def mock_api_call():
            pass

        # Verify exception
        with self.assertRaises(GeminiRateLimitError):
            mock_api_call()

    @patch("src.gemini_tracker.database")
    def test_error_handling_logging(self, mock_db):
        mock_db.get_api_usage_rpm.return_value = 0
        mock_db.get_api_usage_rpd.return_value = 0
        mock_db.get_api_usage_tpm.return_value = 0

        @track_gemini_call
        def failing_api_call():
            raise ValueError("API Error")

        with self.assertRaises(ValueError):
            failing_api_call()

        # Verify logging of failed call
        mock_db.log_api_usage.assert_called_once()
        args, kwargs = mock_db.log_api_usage.call_args
        self.assertEqual(kwargs["tokens_prompt"], 0)
        self.assertEqual(kwargs["tokens_response"], 0)


if __name__ == "__main__":
    unittest.main()
