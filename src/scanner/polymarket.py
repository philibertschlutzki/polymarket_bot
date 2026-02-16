import logging
from typing import Any

import aiohttp
import msgspec
import pandas as pd
from nautilus_trader.adapters.polymarket import parse_polymarket_instrument
from nautilus_trader.adapters.polymarket.common.gamma_markets import \
    normalize_gamma_market_to_clob_format
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

        instruments: list[Instrument] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch markets: {response.status}")
                        return []

                    data = await response.read()
                    # Gamma API returns a list of markets for /markets endpoint
                    # Or check for 'data' key just in case wrapper changes
                    try:
                        markets = msgspec.json.decode(data)
                        if isinstance(markets, dict) and "data" in markets:
                            markets = markets["data"]
                    except Exception:
                        logger.error("Failed to decode Gamma API response")
                        return []

                    if not isinstance(markets, list):
                        logger.error(
                            "Unexpected response format from Gamma API (expected list)"
                        )
                        return []

                    logger.info(f"Fetched {len(markets)} markets. Filtering...")

                    now = pd.Timestamp.now(tz="UTC")
                    max_expiration_date = now + pd.Timedelta(
                        days=self.days_to_expiration
                    )

                    for market in markets:
                        instruments.extend(
                            self._process_market(market, max_expiration_date)
                        )

        except Exception as e:
            logger.error(f"Error during scan: {e}")
            return []

        logger.info(f"Scan complete. Found {len(instruments)} instruments.")
        return instruments

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
            # If missing, we might skip or allow. Let's assume missing = pass or check order book.
            # But we only have summary data here.
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
