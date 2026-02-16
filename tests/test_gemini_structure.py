
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import json
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.intelligence.gemini import GeminiClient

class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Patch the genai module
        self.genai_patcher = patch('src.intelligence.gemini.genai')
        self.mock_genai = self.genai_patcher.start()

        # Mock the GenerativeModel
        self.mock_model = MagicMock()
        self.mock_genai.GenerativeModel.return_value = self.mock_model

        # Ensure generate_content returns a mock object with .text attribute
        self.mock_response = MagicMock()
        self.mock_model.generate_content.return_value = self.mock_response

    def tearDown(self):
        self.genai_patcher.stop()

    def test_initialization(self):
        """Test that GeminiClient initializes correctly."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            client = GeminiClient(config={"gemini": {"model": "test-model"}})
            self.mock_genai.configure.assert_called_with(api_key="fake_key")
            self.mock_genai.GenerativeModel.assert_called()

    async def test_analyze_market_success(self):
        """Test analyze_market with valid JSON response."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            client = GeminiClient()

            expected_result = {
                "action": "buy",
                "target_outcome": "Yes",
                "confidence": 0.85,
                "reasoning": "Positive news found."
            }
            self.mock_response.text = json.dumps(expected_result)

            result = await client.analyze_market("Question", "Description", {"Yes": 0.5}, ["Yes", "No"])

            self.assertEqual(result, expected_result)
            self.mock_model.generate_content.assert_called_once()

    async def test_analyze_market_json_error(self):
        """Test analyze_market handles invalid JSON."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            client = GeminiClient()

            self.mock_response.text = "Invalid JSON"

            result = await client.analyze_market("Question", "Description", {"Yes": 0.5}, ["Yes", "No"])

            self.assertEqual(result["action"], "hold")
            self.assertIn("Analysis failed", result["reasoning"])

if __name__ == '__main__':
    unittest.main()
