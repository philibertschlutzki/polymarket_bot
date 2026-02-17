import asyncio
import logging
import sqlite3
from typing import Any, Callable, List, Optional, Tuple

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.trading.strategy import Strategy

logger = logging.getLogger(__name__)

# Shared queue for strategy events (trades, pnl)
RECORDER_QUEUE: asyncio.Queue[Tuple[str, Any]] = asyncio.Queue(maxsize=10000)


class RecorderConfig(StrategyConfig):
    db_path: str = "src/data/market_data.db"
    batch_size: int = 100
    flush_interval_seconds: float = 5.0


class RecorderStrategy(Strategy):  # type: ignore[misc]
    """
    A strategy that acts as a data recorder, saving ticks to SQLite.
    Optimized for low memory usage via batching and transactions.
    """

    def __init__(self, config: RecorderConfig):
        super().__init__(config)
        self.config = config
        # Use the shared queue
        self.queue = RECORDER_QUEUE
        self.writer_task: Optional[asyncio.Task[None]] = None
        self._running = False

        # Initialize DB synchronously
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.config.db_path) as conn:
                # Enable WAL Mode
                conn.execute("PRAGMA journal_mode=WAL;")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS quotes (
                        timestamp INTEGER,
                        instrument_id TEXT,
                        bid_price REAL,
                        ask_price REAL,
                        bid_size REAL,
                        ask_size REAL
                    )
                """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trades (
                        timestamp INTEGER,
                        instrument_id TEXT,
                        price REAL,
                        size REAL,
                        side TEXT
                    )
                """
                )
                # Table for strategy trades/PnL
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_trades (
                        timestamp INTEGER,
                        instrument_id TEXT,
                        side TEXT,
                        price REAL,
                        quantity REAL,
                        realized_pnl REAL
                    )
                """
                )
                conn.commit()
            logger.info(f"Database initialized at {self.config.db_path} (WAL Mode)")
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
        buffer_quotes: List[Tuple[Any, ...]] = []
        buffer_trades: List[Tuple[Any, ...]] = []
        buffer_bot_trades: List[Tuple[Any, ...]] = []
        last_flush = asyncio.get_running_loop().time()

        def _commit_batch(
            quotes: List[Tuple[Any, ...]],
            trades: List[Tuple[Any, ...]],
            bot_trades: List[Tuple[Any, ...]],
        ) -> None:
            self._execute_batch_insert(quotes, trades, bot_trades)

        try:
            while self._running:
                last_flush = await self._process_loop_iteration(
                    buffer_quotes,
                    buffer_trades,
                    buffer_bot_trades,
                    last_flush,
                    _commit_batch,
                )

        except asyncio.CancelledError:
            logger.info("Writer loop cancelled.")
        except Exception as e:
            logger.error(f"Writer loop unexpected error: {e}")
        finally:
            # Flush remaining data on exit
            try:
                if buffer_quotes or buffer_trades or buffer_bot_trades:
                    await asyncio.to_thread(_commit_batch, buffer_quotes, buffer_trades, buffer_bot_trades)
            except Exception as e:
                logger.error(f"Final DB flush failed: {e}")

    async def _process_loop_iteration(
        self,
        buffer_quotes: List[Tuple[Any, ...]],
        buffer_trades: List[Tuple[Any, ...]],
        buffer_bot_trades: List[Tuple[Any, ...]],
        last_flush: float,
        commit_func: Callable[[List[Tuple[Any, ...]], List[Tuple[Any, ...]], List[Tuple[Any, ...]]], None],
    ) -> float:
        try:
            # Try to get an item with a timeout
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                self._process_item(item, buffer_quotes, buffer_trades, buffer_bot_trades)
            except asyncio.TimeoutError:
                pass  # Continue to check flush conditions

            now = asyncio.get_running_loop().time()

            if self._should_flush(len(buffer_quotes), len(buffer_trades), len(buffer_bot_trades), now, last_flush):
                await asyncio.to_thread(commit_func, buffer_quotes, buffer_trades, buffer_bot_trades)
                buffer_quotes.clear()
                buffer_trades.clear()
                buffer_bot_trades.clear()
                return now

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"DB Write error in loop iteration: {e}")
            # Prevent spin loop on error
            await asyncio.sleep(1.0)

        return last_flush

    def _execute_batch_insert(
        self,
        quotes: List[Tuple[Any, ...]],
        trades: List[Tuple[Any, ...]],
        bot_trades: List[Tuple[Any, ...]],
    ) -> None:
        try:
            with sqlite3.connect(self.config.db_path) as conn:
                with conn:  # Transaction context
                    if quotes:
                        conn.executemany("INSERT INTO quotes VALUES (?,?,?,?,?,?)", quotes)
                    if trades:
                        conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?)", trades)
                    if bot_trades:
                        conn.executemany(
                            "INSERT INTO bot_trades (timestamp, instrument_id, side, "
                            "price, quantity, realized_pnl) VALUES (?,?,?,?,?,?)",
                            bot_trades,
                        )
        except Exception as e:
            logger.error(f"Batch commit failed: {e}")

    def _process_item(
        self,
        item: Tuple[str, Any],
        buffer_quotes: List[Tuple[Any, ...]],
        buffer_trades: List[Tuple[Any, ...]],
        buffer_bot_trades: List[Tuple[Any, ...]],
    ) -> None:
        msg_type, data = item
        if msg_type == "quote":
            qt: QuoteTick = data
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
        elif msg_type == "trade":
            tt: TradeTick = data
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
        elif msg_type == "strategy_trade":
            # Expecting dict: {timestamp, instrument_id, side, price, quantity, realized_pnl}
            d = data
            buffer_bot_trades.append(
                (
                    d["timestamp"],
                    d["instrument_id"],
                    d["side"],
                    d["price"],
                    d["quantity"],
                    d["realized_pnl"],
                )
            )

    def _should_flush(self, quote_len: int, trade_len: int, bot_len: int, now: float, last_flush: float) -> bool:
        return (
            quote_len >= self.config.batch_size
            or trade_len >= self.config.batch_size
            or bot_len >= self.config.batch_size
            or (
                now - last_flush > self.config.flush_interval_seconds
                and (quote_len > 0 or trade_len > 0 or bot_len > 0)
            )
        )
