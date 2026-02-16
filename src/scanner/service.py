import asyncio
import logging
import os
from typing import Any, List

import msgspec
from nautilus_trader.model.instruments import Instrument

from src.scanner.polymarket import PolymarketScanner

logger = logging.getLogger(__name__)


class PeriodicScannerService:
    def __init__(
        self,
        scanner: PolymarketScanner,
        instrument_provider: Any,
        interval_hours: int = 1,
        catalog_path: str = "config/catalog.json",
    ):
        self.scanner = scanner
        self.instrument_provider = instrument_provider
        self.interval = interval_hours * 3600
        self.catalog_path = catalog_path
        self.is_running = False

    async def run(self) -> None:
        """
        Run the periodic scanner loop.
        """
        self.is_running = True
        logger.info(f"Periodic Scanner Service started. Interval: {self.interval}s")

        while self.is_running:
            try:
                await self._perform_scan_cycle()
            except Exception as e:
                logger.error(f"Error in periodic scanner: {e}")

            # Sleep for the interval
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                logger.info("Scanner service cancelled.")
                break

    async def _perform_scan_cycle(self) -> None:
        logger.info("Running periodic scan...")
        instruments = await self.scanner.scan()
        if instruments:
            await self._process_found_instruments(instruments)
        else:
            logger.info("No instruments found.")

    async def _process_found_instruments(self, instruments: List[Instrument]) -> None:
        logger.info(
            f"Scanner found {len(instruments)} instruments. Updating provider..."
        )
        count = 0
        added_instruments = []
        for instrument in instruments:
            try:
                self.instrument_provider.add(instrument)
                count += 1
                added_instruments.append(instrument)
            except Exception as e:
                # Likely already exists
                logger.debug(f"Could not add instrument {instrument.id}: {e}")

        logger.info(f"Registered/Updated {count} instruments.")

        # Persist new instruments to catalog
        if added_instruments:
            await asyncio.to_thread(self._save_catalog, added_instruments)

    def _save_catalog(self, instruments: List[Instrument]) -> None:
        """
        Persist instruments to catalog.json using msgspec.
        Running in a separate thread.
        """
        try:
            os.makedirs(os.path.dirname(self.catalog_path), exist_ok=True)
            data = self._load_existing_catalog()
            existing_ids = {str(d.get("id")) for d in data if isinstance(d, dict)}

            updated = self._update_catalog_data(data, existing_ids, instruments)

            if updated:
                with open(self.catalog_path, "wb") as f:
                    f.write(msgspec.json.encode(data))
                logger.info(f"Persisted catalog to {self.catalog_path}")

        except Exception as e:
            logger.error(f"Failed to save catalog: {e}")

    def _load_existing_catalog(self) -> List[Any]:
        data: List[Any] = []
        if os.path.exists(self.catalog_path):
            try:
                with open(self.catalog_path, "rb") as f:
                    content = f.read()
                    if content:
                        decoded = msgspec.json.decode(content)
                        if isinstance(decoded, list):
                            data = decoded
            except Exception as e:
                logger.warning(f"Failed to load existing catalog: {e}")
        return data

    def _update_catalog_data(
        self, data: List[Any], existing_ids: set[str], instruments: List[Instrument]
    ) -> bool:
        updated = False
        for instr in instruments:
            try:
                # Convert to dict using to_dict() if available (Nautilus standard)
                # Fallback to msgspec.to_builtins for Structs
                item = (
                    instr.to_dict()
                    if hasattr(instr, "to_dict")
                    else msgspec.to_builtins(instr)
                )
                if isinstance(item, dict):
                    # Ensure ID is string for comparison
                    instr_id = str(item.get("id"))
                    if instr_id not in existing_ids:
                        data.append(item)
                        existing_ids.add(instr_id)
                        updated = True
            except Exception as e:
                logger.warning(f"Failed to serialize instrument: {e}")
        return updated

    def stop(self) -> None:
        self.is_running = False
