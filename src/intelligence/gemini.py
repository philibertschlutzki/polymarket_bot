import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

import google.generativeai as genai
from google.generativeai import GenerativeModel  # type: ignore[attr-defined]
from google.generativeai.protos import GoogleSearchRetrieval
from google.generativeai.types import (
    GenerationConfig,
    HarmBlockThreshold,
    HarmCategory,
    Tool,
)

logger = logging.getLogger(__name__)


class CircuitBreakerError(Exception):
    pass


class GeminiClient:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        gemini_config = self.config.get("gemini", {})

        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found in environment variables.")
        else:
            genai.configure(api_key=self.api_key)  # type: ignore[attr-defined]

        self.model_name = os.getenv("GEMINI_MODEL") or str(gemini_config.get("model", "gemini-2.0-flash"))
        self.temperature = float(gemini_config.get("temperature", 0.1))

        # Circuit Breaker State
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3

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
        self.tools: List[Union[Tool, Dict[str, Any]]]
        try:
            self.tools = [Tool(google_search_retrieval=GoogleSearchRetrieval())]
        except AttributeError:
            # Fallback if specific types aren't available (though strict mode might complain)
            logger.warning("GoogleSearchRetrieval type not found, using dict syntax fallback.")
            self.tools = [{"google_search_retrieval": {}}]

        self.model: Optional[GenerativeModel] = None
        try:
            self.model = genai.GenerativeModel(  # type: ignore[attr-defined]
                model_name=self.model_name,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=self.response_schema,
                    temperature=self.temperature,
                ),
                tools=self.tools,
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
        Includes retries with exponential backoff and Circuit Breaker.
        """
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.critical("Circuit Breaker OPEN: Too many consecutive API errors. Skipping analysis.")
            raise CircuitBreakerError("Gemini API Circuit Breaker is OPEN.")

        if not self.model:
            logger.error("Gemini model not initialized.")
            return self._error_result("Model not initialized")

        prompt = self._build_prompt(question, description, prices, available_outcomes)
        retries = 3
        delay = 2.0

        for attempt in range(retries):
            try:
                response = await asyncio.to_thread(self.model.generate_content, prompt)
                result = self._parse_response(response.text)

                # Success - Reset Circuit Breaker
                self.consecutive_errors = 0
                return result

            except Exception as e:
                logger.warning(f"Gemini analysis attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    self.consecutive_errors += 1
                    logger.error(f"Gemini analysis failed. Consecutive errors: {self.consecutive_errors}")

                    if self.consecutive_errors >= self.max_consecutive_errors:
                        logger.critical("Circuit Breaker TRIPPED!")

                    return self._error_result(f"Analysis failed: {str(e)}")

        return self._error_result("Unexpected flow end")

    def _build_prompt(
        self,
        question: str,
        description: str,
        prices: Dict[str, float],
        available_outcomes: List[str],
    ) -> str:
        return f"""
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

    def _parse_response(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        # Clean Markdown code blocks
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            res: Dict[str, Any] = json.loads(text)
            return res
        except json.JSONDecodeError:
            logger.warning("Gemini response was not valid JSON, attempting to extract.")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end != -1:
                res = json.loads(text[start:end])
                return res
            else:
                raise ValueError("No JSON found in response")

    def _error_result(self, reason: str) -> Dict[str, Any]:
        return {
            "action": "hold",
            "target_outcome": "",
            "confidence": 0.0,
            "reasoning": reason,
        }
