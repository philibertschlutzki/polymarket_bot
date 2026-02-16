import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.intelligence.gemini import GeminiSentiment

class TestGeminiSentiment(unittest.TestCase):
    def setUp(self):
        # Patch the genai module
        self.genai_patcher = patch('src.intelligence.gemini.genai')
        self.mock_genai = self.genai_patcher.start()

        # Mock the GenerativeModel
        self.mock_model = MagicMock()
        self.mock_genai.GenerativeModel.return_value = self.mock_model

    def tearDown(self):
        self.genai_patcher.stop()

    def test_initialization(self):
        """Test that GeminiSentiment initializes correctly."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            sentiment = GeminiSentiment()
            self.mock_genai.configure.assert_called_with(api_key="fake_key")
            self.mock_genai.GenerativeModel.assert_called()

    def test_analyze_market_success(self):
        """Test analyze_market with valid JSON response."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            sentiment = GeminiSentiment()

            # Mock the response
            mock_response = MagicMock()
            expected_result = {
                "sentiment": "bullish",
                "confidence": 0.85,
                "reasoning": "Positive news found."
            }
            mock_response.text = json.dumps(expected_result)
            self.mock_model.generate_content.return_value = mock_response

            result = sentiment.analyze_market("Question", "Description", {"Yes": 0.5})

            self.assertEqual(result, expected_result)
            self.mock_model.generate_content.assert_called_once()

            # Verify that response_mime_type="application/json" was used
            # We need to check the call args
            args, kwargs = self.mock_model.generate_content.call_args
            self.assertIn("generation_config", kwargs)

            self.mock_genai.types.GenerationConfig.assert_called_with(
                response_mime_type="application/json",
                temperature=0.1
            )

    def test_analyze_market_json_error(self):
        """Test analyze_market handles invalid JSON."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            sentiment = GeminiSentiment()

            mock_response = MagicMock()
            mock_response.text = "Invalid JSON"
            self.mock_model.generate_content.return_value = mock_response

            result = sentiment.analyze_market("Question", "Description", {"Yes": 0.5})

            self.assertEqual(result["sentiment"], "neutral")
            self.assertIn("JSON parse error", result["reasoning"])

if __name__ == '__main__':
    unittest.main()
