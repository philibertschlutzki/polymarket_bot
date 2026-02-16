import asyncio
import logging
import sqlite3
from typing import Callable, List, Optional, Tuple

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.trading.strategy import Strategy

logger = logging.getLogger(__name__)


class RecorderConfig(StrategyConfig, frozen=True):
    db_path: str = "src/data/market_data.db"
    batch_size: int = 100
    flush_interval_seconds: float = 5.0


class RecorderStrategy(Strategy):
    """
    A strategy that acts as a data recorder, saving ticks to SQLite.
    Optimized for low memory usage via batching and transactions.
    """

    def __init__(self, config: RecorderConfig):
        super().__init__(config)
        self.config = config
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.writer_task: Optional[asyncio.Task] = None
        self._running = False

        # Initialize DB synchronously
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.config.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS quotes (
                        timestamp INTEGER,
                        instrument_id TEXT,
                        bid_price REAL,
                        ask_price REAL,
                        bid_size REAL,
                        ask_size REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        timestamp INTEGER,
                        instrument_id TEXT,
                        price REAL,
                        size REAL,
                        side TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            self.log.error(f"Failed to initialize DB: {e}")

    def on_start(self) -> None:
        self.log.info("RecorderStrategy started.")
        self._running = True
        # Start writer task
        self.writer_task = asyncio.create_task(self._writer_loop())

        # Subscribe to all currently available instruments
        for instrument in self.cache.instruments():
            self.subscribe_quote_ticks(instrument.id)
            self.subscribe_trade_ticks(instrument.id)
            self.log.info(f"Recorder subscribed to {instrument.id}")

    def on_stop(self) -> None:
        self.log.info("RecorderStrategy stopping...")
        self._running = False
        if self.writer_task:
            self.writer_task.cancel()

    def on_quote_tick(self, tick: QuoteTick) -> None:
        try:
            self.queue.put_nowait(("quote", tick))
        except asyncio.QueueFull:
            pass

    def on_trade_tick(self, tick: TradeTick) -> None:
        try:
            self.queue.put_nowait(("trade", tick))
        except asyncio.QueueFull:
            pass

    async def _writer_loop(self) -> None:
        """
        Background task to write data to SQLite in batches.
        """
        buffer_quotes: List[Tuple] = []
        buffer_trades: List[Tuple] = []
        last_flush = asyncio.get_running_loop().time()

        conn = sqlite3.connect(
            self.config.db_path, check_same_thread=False
        )  # Safe as only this task writes

        def _commit_batch(quotes: list, trades: list) -> None:
            if quotes:
                conn.executemany("INSERT INTO quotes VALUES (?,?,?,?,?,?)", quotes)
            if trades:
                conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?)", trades)
            conn.commit()

        try:
            while self._running:
                last_flush = await self._process_loop_iteration(
                    buffer_quotes, buffer_trades, last_flush, _commit_batch
                )

        finally:
            # Flush remaining data on exit
            try:
                if buffer_quotes or buffer_trades:
                    _commit_batch(buffer_quotes, buffer_trades)
            except Exception as e:
                logger.error(f"Final DB flush failed: {e}")
            finally:
                conn.close()

    async def _process_loop_iteration(
        self,
        buffer_quotes: list,
        buffer_trades: list,
        last_flush: float,
        commit_func: Callable[[list, list], None],
    ) -> float:
        try:
            # Try to get an item with a timeout
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                self._process_item(item, buffer_quotes, buffer_trades)
            except asyncio.TimeoutError:
                pass  # Continue to check flush conditions

            now = asyncio.get_running_loop().time()

            if self._should_flush(
                len(buffer_quotes), len(buffer_trades), now, last_flush
            ):
                await asyncio.to_thread(commit_func, buffer_quotes, buffer_trades)
                buffer_quotes.clear()
                buffer_trades.clear()
                return now

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"DB Write error: {e}")
            # Prevent spin loop on error
            await asyncio.sleep(1.0)

        return last_flush

    def _process_item(self, item: tuple, buffer_quotes: list, buffer_trades: list):
        if item[0] == "quote":
            qt: QuoteTick = item[1]
            buffer_quotes.append(
                (
                    qt.ts_event,
                    qt.instrument_id.value,
                    qt.bid_price.as_double(),
                    qt.ask_price.as_double(),
                    qt.bid_size.as_double(),
                    qt.ask_size.as_double(),
                )
            )
        elif item[0] == "trade":
            tt: TradeTick = item[1]
            side_str = tt.side.name if hasattr(tt.side, "name") else str(tt.side)
            buffer_trades.append(
                (
                    tt.ts_event,
                    tt.instrument_id.value,
                    tt.price.as_double(),
                    tt.size.as_double(),
                    side_str,
                )
            )

    def _should_flush(
        self, quote_len: int, trade_len: int, now: float, last_flush: float
    ) -> bool:
        return (
            quote_len >= self.config.batch_size
            or trade_len >= self.config.batch_size
            or (
                now - last_flush > self.config.flush_interval_seconds
                and (quote_len > 0 or trade_len > 0)
            )
        )
