import asyncio
import logging
from typing import Any, Dict, List, Optional, TypeAlias, cast

import aiohttp
import msgspec
import pandas as pd
from nautilus_trader.adapters.polymarket.common.parsing import parse_instrument
from nautilus_trader.model.instruments import Instrument

logger = logging.getLogger(__name__)

MarketData: TypeAlias = Dict[str, Any]


class PolymarketScanner:
    """
    Scanner for fetching and filtering Polymarket instruments via Gamma API.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the scanner with configuration.

        Args:
            config: The application configuration dictionary.
        """
        self.config = config
        self.base_url = "https://gamma-api.polymarket.com"
        scanner_config: Dict[str, Any] = config.get("scanner", {})
        self.min_daily_volume = float(scanner_config.get("min_daily_volume", 1000.0))
        self.max_spread = float(scanner_config.get("max_spread", 0.05))
        self.days_to_expiration = int(scanner_config.get("days_to_expiration", 7))

    async def scan(self) -> List[Instrument]:
        """
        Scan Polymarket for opportunities.
        Retries with exponential backoff on failure.

        Returns:
            List[Instrument]: A list of filtered Nautilus Trader Instruments.
        """
        logger.info("Starting market scan...")

        params = {
            "limit": 100,
            "active": "true",
            "closed": "false",
            "archived": "false",
            "volume_num_min": self.min_daily_volume,
            "order": "volume",
            "ascending": "false",
        }

        url = f"{self.base_url}/markets"
        retries = 3
        delay = 2.0

        for attempt in range(retries):
            try:
                markets = await self._fetch_markets(url, params)
                if markets is None:
                    if attempt < retries - 1:
                        logger.warning(
                            f"Scan attempt {attempt+1} failed. Retrying in {delay}s..."
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                    continue

                logger.info(f"Fetched {len(markets)} markets. Filtering...")

                instruments: List[Instrument] = []
                now = pd.Timestamp.now(tz="UTC")
                max_expiration_date = now + pd.Timedelta(days=self.days_to_expiration)

                for market in markets:
                    instruments.extend(
                        self._process_market(market, max_expiration_date)
                    )

                logger.info(f"Scan complete. Found {len(instruments)} instruments.")
                return instruments

            except Exception as e:
                logger.warning(f"Error during scan attempt {attempt+1}/{retries}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2

        logger.error("All scan attempts failed.")
        return []

    async def _fetch_markets(
        self, url: str, params: Dict[str, Any]
    ) -> Optional[List[MarketData]]:
        """
        Helper to fetch markets from API.

        Args:
            url: The API endpoint URL.
            params: The query parameters.

        Returns:
            Optional[List[MarketData]]: A list of market data dicts or None if failed.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.warning(
                            f"Failed to fetch markets (Status {response.status})"
                        )
                        return None

                    data = await response.read()
                    try:
                        markets_data = msgspec.json.decode(data)
                        markets: List[MarketData] = []
                        if isinstance(markets_data, dict) and "data" in markets_data:
                            markets = cast(List[MarketData], markets_data["data"])
                        elif isinstance(markets_data, list):
                            markets = cast(List[MarketData], markets_data)
                        else:
                            logger.error("Unexpected response format from Gamma API")
                            return None
                        return markets
                    except Exception as e:
                        logger.error(f"Failed to decode Gamma API response: {e}")
                        return None
        except Exception as e:
            logger.error(f"Network error fetching markets: {e}")
            return None

    def _process_market(
        self, market: MarketData, max_expiration_date: pd.Timestamp
    ) -> List[Instrument]:
        """
        Process a single market and return valid instruments.

        Args:
            market: The market data dictionary.
            max_expiration_date: The cutoff date for expiration.

        Returns:
            List[Instrument]: Valid instruments extracted from the market.
        """
        instruments: List[Instrument] = []
        try:
            # Normalize
            clob_market = self._normalize_market(market)

            if not self._validate_market_filters(clob_market, max_expiration_date):
                return []

            # Parse Instruments
            tokens = clob_market.get("tokens", [])
            ts_init = int(pd.Timestamp.now().value)

            for token in tokens:
                token_id = token.get("tokenId") or token.get("token_id")
                outcome = token.get("outcome")

                if token_id and outcome:
                    instrument = parse_instrument(
                        market_info=clob_market,
                        token_id=token_id,
                        outcome=outcome,
                        ts_init=ts_init,
                    )
                    instruments.append(instrument)

        except Exception as e:
            logger.debug(f"Failed to parse market {market.get('id')}: {e}")

        return instruments

    def _normalize_market(self, gamma_market: MarketData) -> MarketData:
        """
        Normalize Gamma API market data to CLOB format expected by parse_instrument.
        """
        return {
            "condition_id": gamma_market.get("conditionId"),
            "question": gamma_market.get("question"),
            "minimum_tick_size": gamma_market.get("minimumTickSize", "0.01"),
            "minimum_order_size": gamma_market.get("minimumOrderSize", 1),
            "end_date_iso": gamma_market.get("endDate"),
            "maker_base_fee": gamma_market.get("makerBaseFee", 0),
            "taker_base_fee": gamma_market.get("takerBaseFee", 0),
            "tokens": gamma_market.get("tokens", []),
            "spread": gamma_market.get("spread", 0.0),  # Preserve spread if present
            **gamma_market,
        }

    def _validate_market_filters(
        self, clob_market: Dict[str, Any], max_expiration_date: pd.Timestamp
    ) -> bool:
        """
        Check spread and expiration filters.
        """
        # Filter by Spread
        spread = clob_market.get("spread")
        if spread is not None and isinstance(spread, (int, float)):
            if spread > self.max_spread:
                return False

        # Filter by expiration
        end_date_iso = clob_market.get("end_date_iso")
        if end_date_iso:
            try:
                expiration = pd.Timestamp(end_date_iso)
                if expiration.tz is None:
                    expiration = expiration.tz_localize("UTC")

                if expiration > max_expiration_date:
                    return False
            except ValueError:
                pass  # Ignore invalid date format

        return True
