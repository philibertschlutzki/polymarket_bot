import json
import logging
import os
from typing import Any, Dict

import google.generativeai as genai

logger = logging.getLogger(__name__)


class GeminiSentiment:
    """
    Wrapper for Google Gemini 2.0 API with Search Grounding capabilities.

    This class handles the initialization of the Gemini model, configuring it
    to use Google Search for real-time information retrieval (Grounding),
    and processing market analysis requests to determine market sentiment.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash-exp"):
        """
        Initializes the GeminiSentiment analyzer.

        Args:
            model_name (str): The name of the Gemini model to use.
                              Defaults to "gemini-2.0-flash-exp".
        """
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found in environment variables.")

        genai.configure(api_key=self.api_key)

        self.model_name = model_name

        # Configure the model with Google Search Grounding.
        # Using the Tool object for robustness and configurability.
        # This requires the google-generativeai SDK.
        try:
            # The tool configuration enables the model to perform dynamic retrieval
            # from Google Search when the query requires external knowledge.
            # dynamic_threshold controls how eager the model is to search (0.3 is a balanced default).
            self.tools = [
                genai.protos.Tool(
                    google_search_retrieval=genai.protos.GoogleSearchRetrieval(
                        dynamic_retrieval_config=genai.protos.DynamicRetrievalConfig(
                            mode=genai.protos.DynamicRetrievalConfig.Mode.MODE_DYNAMIC,
                            dynamic_threshold=0.3,
                        )
                    )
                )
            ]
            self.model = genai.GenerativeModel(
                model_name=self.model_name, tools=self.tools
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize model with Google Search Grounding: {e}. Falling back to no tools."
            )
            # Fallback to model without tools, but log an error.
            self.model = genai.GenerativeModel(model_name=self.model_name)

    def analyze_market(
        self, question: str, description: str, prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Analyzes the market sentiment using Gemini with Search Grounding.

        Args:
            question (str): The market question (e.g. "Will Bitcoin hit 100k?").
            description (str): The market description providing context.
            prices (Dict[str, float]): A dictionary of current prices (e.g. {"Yes": 0.6, "No": 0.4}).

        Returns:
            Dict[str, Any]: A dictionary containing:
                - sentiment (str): "bullish", "bearish", or "neutral".
                - confidence (float): Confidence score between 0.0 and 1.0.
                - reasoning (str): Explanation of the analysis.
        """

        prompt = f"""
        You are a professional quantitative trader analyzing a prediction market on Polymarket.

        Market Question: {question}
        Description: {description}
        Current Prices: {json.dumps(prices)}

        Your task is to:
        1. Use Google Search to find the latest news and information relevant to this market.
        2. Analyze the sentiment based on the news and current market prices.
        3. Determine if the current price offers a good risk/reward ratio for a swing trade.

        Output must be a valid JSON object with the following schema:
        {{
            "sentiment": "bullish" | "bearish" | "neutral",
            "confidence": float (0.0 to 1.0),
            "reasoning": "Concise explanation of your analysis, citing sources if possible."
        }}
        """

        try:
            # Enforce JSON output using response_mime_type.
            # This ensures the model returns a valid JSON string, which is crucial for
            # programmatic parsing in the next step.
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json", temperature=0.1
            )

            response = self.model.generate_content(
                prompt, generation_config=generation_config
            )

            # Parse the response
            try:
                result = json.loads(response.text)
                return result
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON response: {e}. Response text: {response.text}"
                )
                return {
                    "sentiment": "neutral",
                    "confidence": 0.0,
                    "reasoning": "JSON parse error",
                }
            except (
                ValueError
            ) as e:  # Handle cases where response.text might be empty or invalid
                logger.error(f"Value error accessing response text: {e}")
                return {
                    "sentiment": "neutral",
                    "confidence": 0.0,
                    "reasoning": f"Response error: {str(e)}",
                }

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return {
                "sentiment": "neutral",
                "confidence": 0.0,
                "reasoning": f"API error: {str(e)}",
            }
