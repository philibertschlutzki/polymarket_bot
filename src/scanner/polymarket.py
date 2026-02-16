import asyncio
import logging
from typing import Any

import aiohttp
import msgspec
import pandas as pd
from nautilus_trader.adapters.polymarket import (
    parse_polymarket_instrument,  # type: ignore[attr-defined]
)
from nautilus_trader.adapters.polymarket.common.gamma_markets import (
    normalize_gamma_market_to_clob_format,
)
from nautilus_trader.model.instruments import Instrument

logger = logging.getLogger(__name__)


class PolymarketScanner:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_url = "https://gamma-api.polymarket.com"
        scanner_config = config.get("scanner", {})
        self.min_daily_volume = float(scanner_config.get("min_daily_volume", 1000.0))
        self.max_spread = float(scanner_config.get("max_spread", 0.05))
        self.days_to_expiration = int(scanner_config.get("days_to_expiration", 7))
        # Additional filters can be added here

    async def scan(self) -> list[Instrument]:
        """
        Scan Polymarket for opportunities.
        Retries with exponential backoff on failure.
        """
        logger.info("Starting market scan...")

        # We can use server-side filters for some parameters
        # volume_num_min is supported by Gamma API
        params = {
            "limit": 100,  # Fetch top 100 first
            "active": "true",
            "closed": "false",
            "archived": "false",
            "volume_num_min": self.min_daily_volume,
            "order": "volume",  # Order by volume descending
            "ascending": "false",
        }

        url = f"{self.base_url}/markets"

        retries = 3
        delay = 2.0

        for attempt in range(retries):
            try:
                markets = await self._fetch_markets(url, params)
                if markets is None:
                    # Failed but handled, retry
                    if attempt < retries - 1:
                        await asyncio.sleep(delay)
                        delay *= 2
                    continue

                logger.info(f"Fetched {len(markets)} markets. Filtering...")

                instruments: list[Instrument] = []
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
        self, url: str, params: dict[str, Any]
    ) -> list[Any] | None:
        """Helper to fetch markets from API."""
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
                    markets = []
                    if isinstance(markets_data, dict) and "data" in markets_data:
                        markets = markets_data["data"]
                    elif isinstance(markets_data, list):
                        markets = markets_data
                    else:
                        logger.error("Unexpected response format from Gamma API")
                        return None
                    return markets
                except Exception as e:
                    logger.error(f"Failed to decode Gamma API response: {e}")
                    raise e

    def _process_market(
        self, market: dict[str, Any], max_expiration_date: pd.Timestamp
    ) -> list[Instrument]:
        """
        Process a single market and return valid instruments.
        """
        instruments = []
        try:
            # Normalize
            clob_market = normalize_gamma_market_to_clob_format(market)

            # Filter by Spread
            # Note: Gamma API 'spread' field might be missing or 0.0 if not calculated
            # We check if it exists and filter if > max_spread.
            spread = clob_market.get("spread")
            if spread is not None and spread > self.max_spread:
                return []

            # Filter by expiration
            end_date_iso = clob_market.get("end_date_iso")
            if end_date_iso:
                try:
                    expiration = pd.Timestamp(end_date_iso)
                    if expiration.tz is None:
                        expiration = expiration.tz_localize("UTC")

                    if expiration > max_expiration_date:
                        return []
                except ValueError:
                    pass  # Ignore invalid date format

            # Parse Instruments
            for token in clob_market["tokens"]:
                token_id = token["token_id"]
                outcome = token["outcome"]

                instrument = parse_polymarket_instrument(
                    market_info=clob_market,
                    token_id=token_id,
                    outcome=outcome,
                )
                instruments.append(instrument)

        except Exception as e:
            logger.debug(f"Failed to parse market {market.get('id')}: {e}")

        return instruments
