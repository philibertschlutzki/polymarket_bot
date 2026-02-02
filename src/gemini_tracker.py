"""
Gemini API Usage Tracker with automatic logging and rate limiting.
"""

import logging
import time
from functools import wraps
from typing import Any

from src import database

# Get dedicated API logger (assumes setup_api_logging is called in main)
# Or we can get it here.
api_logger = logging.getLogger("api_metrics")
logger = logging.getLogger(__name__)

# Gemini API Limits (according to Google AI Studio Free Tier)
GEMINI_RPM_LIMIT = 15
GEMINI_RPD_LIMIT = 1500
GEMINI_TPM_LIMIT = 1_000_000


class GeminiRateLimitError(Exception):
    """Raised when Gemini API rate limit is exceeded."""

    pass


def track_gemini_call(func):
    """
    Decorator to track Gemini API usage and enforce rate limits.

    Usage:
        @track_gemini_call
        def my_gemini_function():
            response = model.generate_content(prompt)
            return response
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()

        # Pre-flight rate limit check
        _check_rate_limits()

        # Execute API call
        try:
            result = func(*args, **kwargs)

            # Extract and log usage metadata
            _log_usage_from_response(
                result=result,
                function_name=func.__name__,
                elapsed_time=time.time() - start_time,
            )

            return result

        except Exception as e:
            # Log failed attempt
            # Use api_logger for consistency if initialized, else standard logger
            target_logger = api_logger if api_logger.handlers else logger
            target_logger.error(f"Gemini API call failed in {func.__name__}: {e}")

            # Still log the call attempt (even if failed)
            database.log_api_usage(
                api_name="gemini",
                endpoint=func.__name__,
                tokens_prompt=0,
                tokens_response=0,
                response_time_ms=int((time.time() - start_time) * 1000),
            )
            raise

    return wrapper


def _check_rate_limits():
    """Check if current usage is within rate limits."""
    rpm = database.get_api_usage_rpm("gemini")
    rpd = database.get_api_usage_rpd("gemini")
    tpm = database.get_api_usage_tpm("gemini")

    if rpm >= GEMINI_RPM_LIMIT:
        wait_time = 60
        api_logger.warning(
            f"⚠️ RPM limit reached ({rpm}/{GEMINI_RPM_LIMIT}). "
            f"Waiting {wait_time}s..."
        )
        time.sleep(wait_time)

    if rpd >= GEMINI_RPD_LIMIT:
        raise GeminiRateLimitError(
            f"Daily request limit reached ({rpd}/{GEMINI_RPD_LIMIT}). "
            "Bot will resume tomorrow."
        )

    if tpm >= GEMINI_TPM_LIMIT:
        wait_time = 60
        api_logger.warning(
            f"⚠️ TPM limit reached ({tpm}/{GEMINI_TPM_LIMIT}). "
            f"Waiting {wait_time}s..."
        )
        time.sleep(wait_time)


def _log_usage_from_response(result: Any, function_name: str, elapsed_time: float):
    """Extract usage metadata from Gemini response and log it."""
    tokens_prompt = 0
    tokens_response = 0

    # Extract token usage from response
    if hasattr(result, "usage_metadata") and result.usage_metadata:
        metadata = result.usage_metadata
        tokens_prompt = getattr(metadata, "prompt_token_count", 0)
        tokens_response = getattr(metadata, "candidates_token_count", 0)

    # Calculate response time
    response_time_ms = int(elapsed_time * 1000)

    # Log to database
    database.log_api_usage(
        api_name="gemini",
        endpoint=function_name,
        tokens_prompt=tokens_prompt,
        tokens_response=tokens_response,
        response_time_ms=response_time_ms,
    )

    # Detailed logging
    # Use api_logger if configured, otherwise fallback to standard logger
    target_logger = api_logger if api_logger.handlers else logger

    total_tokens = tokens_prompt + tokens_response
    rpm = database.get_api_usage_rpm('gemini')

    target_logger.info(
        f"📊 Gemini API: {function_name} | "
        f"Tokens: {tokens_prompt}→{tokens_response} ({total_tokens} total) | "
        f"Time: {response_time_ms}ms | "
        f"RPM: {rpm}/{GEMINI_RPM_LIMIT}"
    )


def log_gemini_usage_manual(
    tokens_prompt: int,
    tokens_response: int,
    endpoint: str = "manual_call",
    response_time_ms: int = 0,
):
    """
    Manually log Gemini API usage when decorator cannot be used.

    Use this in contexts where the decorator is not applicable.
    """
    database.log_api_usage(
        api_name="gemini",
        endpoint=endpoint,
        tokens_prompt=tokens_prompt,
        tokens_response=tokens_response,
        response_time_ms=response_time_ms,
    )
