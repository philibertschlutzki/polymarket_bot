import asyncio
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from nautilus_trader.model.instruments import Instrument

from src.scanner.polymarket import PolymarketScanner


@pytest.mark.asyncio
async def test_scanner_scan_success(config: Dict[str, Any]) -> None:
    scanner = PolymarketScanner(config)

    # Mock parse_instrument
    with patch("src.scanner.polymarket.parse_instrument") as mock_parse, patch.object(scanner, "_fetch_markets") as mock_fetch:
        # Mock Data from API
        mock_fetch.return_value = [
            {
                "conditionId": "cond1",
                "question": "Will it rain?",
                "slug": "rain",
                "endDate": (pd.Timestamp.now("UTC") + pd.Timedelta(days=1)).isoformat(),
                "tokens": [{"tokenId": "123", "outcome": "Yes"}, {"tokenId": "456", "outcome": "No"}],
                "spread": 0.01,
            }
        ]

        mock_instrument = MagicMock(spec=Instrument)
        mock_parse.return_value = mock_instrument

        # Execute
        instruments = await scanner.scan()

        # Assertions
        assert len(instruments) == 2
        mock_fetch.assert_called_once()
        assert mock_parse.call_count == 2


@pytest.mark.asyncio
async def test_scanner_filter_spread(config: Dict[str, Any]) -> None:
    scanner = PolymarketScanner(config)

    with patch.object(scanner, "_fetch_markets") as mock_fetch:
        mock_fetch.return_value = [{"spread": 0.10, "tokens": [{"tokenId": "1", "outcome": "Yes"}]}]  # > 0.05

        instruments = await scanner.scan()
        assert len(instruments) == 0


@pytest.mark.asyncio
async def test_scanner_filter_expiration(config: Dict[str, Any]) -> None:
    scanner = PolymarketScanner(config)

    with patch.object(scanner, "_fetch_markets") as mock_fetch:
        future_date = pd.Timestamp.now("UTC") + pd.Timedelta(days=8)
        mock_fetch.return_value = [
            {"spread": 0.01, "endDate": future_date.isoformat(), "tokens": [{"tokenId": "1", "outcome": "Yes"}]}
        ]

        instruments = await scanner.scan()
        assert len(instruments) == 0


@pytest.mark.asyncio
async def test_scanner_retry_logic(config: Dict[str, Any]) -> None:
    scanner = PolymarketScanner(config)

    with patch.object(scanner, "_fetch_markets") as mock_fetch:
        mock_fetch.side_effect = [None, None, []]
        await scanner.scan()
        assert mock_fetch.call_count == 3
