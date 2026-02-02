import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import requests
from tenacity import RetryError
from src.main import graphql_request_with_retry, _generate_gemini_response

class TestLoggingLogic(unittest.TestCase):

    @patch('src.main.requests.post')
    @patch('src.main.logger')
    def test_graphql_logging_success(self, mock_logger, mock_post):
        """Test GraphQL logging on success"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"market": {"id": "1"}}}
        mock_response.headers = {"Content-Type": "application/json"}
        mock_post.return_value = mock_response

        result = graphql_request_with_retry("query { test }")

        self.assertIsNotNone(result)
        # Check if debug logs were called
        self.assertTrue(mock_logger.debug.called)

    @patch('src.main.requests.post')
    @patch('src.main.logger')
    def test_graphql_logging_404(self, mock_logger, mock_post):
        """Test GraphQL logging on 404"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_post.return_value = mock_response

        result = graphql_request_with_retry("query { test }")

        self.assertIsNone(result)
        # Check if error logs were called
        self.assertTrue(mock_logger.error.called)

    @patch('src.main.genai.Client')
    @patch('src.main.logger')
    def test_gemini_logging_success(self, mock_logger, mock_client_cls):
        """Test Gemini logging on success"""
        mock_client = mock_client_cls.return_value
        mock_response = Mock()
        mock_response.text = '```json\n{"estimated_probability": 0.5, "confidence_score": 0.8, "reasoning": "test"}\n```'
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.usage_metadata.total_token_count = 20

        mock_client.models.generate_content.return_value = mock_response

        # _generate_gemini_response requires a client and prompt
        result, meta = _generate_gemini_response(mock_client, "test prompt")

        self.assertIsNotNone(result)
        self.assertTrue(mock_logger.debug.called)

    @patch('src.main.genai.Client')
    @patch('src.main.logger')
    def test_gemini_logging_json_error(self, mock_logger, mock_client_cls):
        """Test Gemini logging on JSON error"""
        mock_client = mock_client_cls.return_value
        mock_response = Mock()
        mock_response.text = 'Invalid JSON'

        # Mock usage metadata to avoid attribute error before json parsing
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.usage_metadata.total_token_count = 20

        mock_client.models.generate_content.return_value = mock_response

        # tenacity raises RetryError after retries are exhausted
        with self.assertRaises(RetryError):
             _generate_gemini_response(mock_client, "test prompt")

        self.assertTrue(mock_logger.error.called)

if __name__ == '__main__':
    unittest.main()
