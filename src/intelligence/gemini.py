import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from google.generativeai import GenerativeModel  # type: ignore[attr-defined]
from google.generativeai.types import HarmBlockThreshold, HarmCategory

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        gemini_config = self.config.get("gemini", {})

        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found in environment variables.")
        else:
            genai.configure(api_key=self.api_key)  # type: ignore[attr-defined]

        self.model_name = str(gemini_config.get("model", "gemini-2.0-flash-exp"))
        self.temperature = float(gemini_config.get("temperature", 0.1))

        # JSON Schema for structured output
        self.response_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                "target_outcome": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
            },
            "required": ["action", "target_outcome", "confidence", "reasoning"],
        }

        # Tools configuration for Search Grounding
        tools: List[Dict[str, Any]] = [{"google_search_retrieval": {}}]

        self.model: Optional[GenerativeModel] = None
        try:
            self.model = genai.GenerativeModel(  # type: ignore[attr-defined]
                model_name=self.model_name,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=self.response_schema,
                    temperature=self.temperature,
                ),
                tools=tools,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
            )
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            self.model = None

    async def analyze_market(
        self,
        question: str,
        description: str,
        prices: Dict[str, float],
        available_outcomes: List[str],
    ) -> Dict[str, Any]:
        """
        Analyze a market using Gemini 2.0 with Search Grounding.
        Includes retries with exponential backoff.
        """
        if not self.model:
            logger.error("Gemini model not initialized.")
            return self._error_result("Model not initialized")

        prompt = f"""
        You are a professional prediction market analyst.
        Analyze the following market and decide on a trading action.

        **Market Question:** {question}
        **Description:** {description}
        **Current Prices:** {prices}
        **Available Outcomes:** {available_outcomes}

        **Instructions:**
        1. Use Google Search to find the latest news and information related to this event.
        2. Evaluate the probability of each outcome based on the information found.
        3. Compare your estimated probability with the implied probability from current prices.
        4. Decide if there is a profitable opportunity (Buy if undervalued, Sell if overvalued/holding, Hold otherwise).
        5. Select the `target_outcome` from the **Available Outcomes** list strictly.
        6. Provide a confidence score (0.0 to 1.0) and a short reasoning.

        Return the result in strict JSON format.
        """

        retries = 3
        delay = 2.0

        for attempt in range(retries):
            try:
                # Generate content in a separate thread
                response = await asyncio.to_thread(self.model.generate_content, prompt)

                # Parse JSON
                try:
                    result: Dict[str, Any] = json.loads(response.text)
                except json.JSONDecodeError:
                    logger.warning(
                        "Gemini response was not valid JSON, attempting to extract."
                    )
                    start = response.text.find("{")
                    end = response.text.rfind("}") + 1
                    if start != -1 and end != -1:
                        result = json.loads(response.text[start:end])
                    else:
                        raise ValueError("No JSON found in response")

                return result

            except Exception as e:
                logger.warning(f"Gemini analysis attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error("All Gemini analysis attempts failed.")
                    return self._error_result(f"Analysis failed: {str(e)}")

        return self._error_result("Unexpected flow end")

    def _error_result(self, reason: str) -> Dict[str, Any]:
        return {
            "action": "hold",
            "target_outcome": "",
            "confidence": 0.0,
            "reasoning": reason,
        }
