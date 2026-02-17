import asyncio
import logging
from typing import Any, Dict

import pytest

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def config() -> Dict[str, Any]:
    return {
        "scanner": {
            "min_daily_volume": 1000.0,
            "max_spread": 0.05,
            "days_to_expiration": 7,
        },
        "gemini": {"model": "gemini-test", "temperature": 0.0},
        "risk": {"max_position_size_usdc": 100.0, "slippage_tolerance_ticks": 2},
        "trading": {"mode": "paper"},
    }
