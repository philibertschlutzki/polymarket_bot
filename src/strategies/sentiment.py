import asyncio
import sqlite3
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

from src.intelligence.gemini import GeminiClient
from src.notifications import TelegramNotifier
from src.data.recorder import RECORDER_QUEUE


class GeminiSentimentConfig(StrategyConfig):
    risk_max_position_size_usdc: float = 50.0
    risk_slippage_tolerance_ticks: int = 2
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_temperature: float = 0.1
    analysis_interval_hours: int = 24
    stop_loss_pct: float = 0.15
    take_profit_pct: float = 0.30
    trading_mode: str = "paper"
    daily_loss_limit_usdc: float = 100.0


class GeminiSentimentStrategy(Strategy):  # type: ignore[misc]
    def __init__(self, config: GeminiSentimentConfig):
        super().__init__(config)
        self.config = config

        # Initialize components
        self.gemini = GeminiClient(
            config={
                "gemini": {
                    "model": self.config.gemini_model,
                    "temperature": self.config.gemini_temperature,
                }
            }
        )
        self.notifier = TelegramNotifier()

        self.analyzed_markets: Set[str] = set()
        self.local_entry_prices: Dict[str, float] = {}
        self.subscribed_instruments: Set[Any] = set()
        self.daily_pnl: float = 0.0
        self.db_path = "src/data/market_data.db"

    def on_start(self) -> None:
        """
        Actions to be performed on strategy start.
        """
        self.log.info(f"GeminiSentimentStrategy started in {self.config.trading_mode.upper()} mode.")
        mode_prefix = "[PAPER] " if self.config.trading_mode == "paper" else ""
        self.notifier.send_message(f"{mode_prefix}🚀 Bot V2 Started. Strategy: Gemini Sentiment Analysis.")

        # Initialize state from DB (Sync, only on start)
        self._init_pnl_state()

        # Subscribe to data for all registered instruments
        self.check_new_instruments()

        # Schedule periodic analysis
        self.clock.schedule(
            self.evaluate_markets,
            interval=timedelta(hours=self.config.analysis_interval_hours),
        )

        # Schedule periodic instrument check (Cold Start fix)
        self.clock.schedule(
            self.check_new_instruments,
            interval=timedelta(minutes=5)
        )

        # Smart Reconciliation
        self._handle_reconciliation()

    def _init_pnl_state(self) -> None:
        """Initialize the PnL state from DB synchronously."""
        try:
            # UTC Midnight
            today_start = int(time.time() // 86400 * 86400)
            with sqlite3.connect(self.db_path) as conn:
                try:
                    cursor = conn.execute(
                        "SELECT SUM(realized_pnl) FROM bot_trades WHERE timestamp >= ?",
                        (today_start,),
                    )
                    result = cursor.fetchone()
                    self.daily_pnl = result[0] if result and result[0] else 0.0
                except sqlite3.OperationalError:
                    # Table might not exist yet. PnL is 0.0
                    self.log.warning("bot_trades table not found during PnL init. Assuming 0.0 PnL.")
                    self.daily_pnl = 0.0

            self.log.info(f"Initialized Daily PnL: {self.daily_pnl:.2f}")
        except Exception as e:
            self.log.error(f"Failed to init PnL state: {e}")

    def check_new_instruments(self, time_event: Optional[int] = None) -> None:
        """
        Check for new instruments in cache and subscribe.
        """
        count = 0
        for instrument in self.cache.instruments():
            if instrument.id not in self.subscribed_instruments:
                self.subscribe_quote_ticks(instrument.id)
                self.subscribed_instruments.add(instrument.id)
                count += 1

        if count > 0:
            self.log.info(f"Subscribed to {count} new instruments.")

    def _handle_reconciliation(self) -> None:
        """
        Handle existing positions on startup.
        """
        positions = self.cache.positions()
        if not positions:
            return

        self.log.info(f"Reconciling {len(positions)} positions...")

        for position in positions:
            self._ensure_position_in_db(position)

            # Immediate Analysis
            instrument = self.cache.instrument(position.instrument_id)
            if instrument and instrument.info:
                question = instrument.info.get("question")
                if question:
                    related = [i for i in self.cache.instruments() if i.info.get("question") == question]
                    if related:
                        asyncio.create_task(self._process_market_async(question, related))

    def _ensure_position_in_db(self, position: Any) -> None:
        """
        Ensure position is tracked (logging fake trade to recorder).
        """
        try:
            instr_id = position.instrument_id.value

            # Logic: If we are reconciling, we just assume we need to set the entry price locally.
            # We don't check DB here to avoid blocking. We just log a reconciliation event.

            quote = self.cache.quote(position.instrument_id)
            price = 0.5
            if quote:
                price = (quote.bid_price.as_double() + quote.ask_price.as_double()) / 2.0

            if price <= 0:
                trade = self.cache.trade(position.instrument_id)
                price = trade.price.as_double() if trade else 0.5

            self.local_entry_prices[instr_id] = price

            ts = int(time.time())
            qty = position.quantity.as_double()
            side = "BUY"

            self.log.info(f"Reconciliation: Logging Fake Trade for {instr_id} @ {price}")

            # Send to Recorder
            data = {
                "timestamp": ts,
                "instrument_id": instr_id,
                "side": side,
                "price": price,
                "quantity": qty,
                "realized_pnl": 0.0 # Fake trade has 0 PnL
            }
            RECORDER_QUEUE.put_nowait(("strategy_trade", data))

        except Exception as e:
            self.log.error(f"Failed to reconcile position {position.instrument_id}: {e}")

    def on_order_filled(self, event: OrderFilled) -> None:
        """
        Record execution and calculate PnL.
        """
        try:
            ts = int(time.time())
            instr_id = event.instrument_id.value
            side = event.order_side.name if hasattr(event.order_side, "name") else str(event.order_side)
            price = event.last_px.as_double()
            qty = event.last_qty.as_double()
            realized_pnl = 0.0

            if side == "BUY":
                self.local_entry_prices[instr_id] = price

            if side == "SELL":
                entry_price = self.local_entry_prices.get(instr_id, 0.0)
                if entry_price <= 0:
                    position = self.cache.position(event.instrument_id)
                    if position:
                        entry_price = position.avg_px_open.as_double()

                if entry_price > 0:
                    realized_pnl = (price - entry_price) * qty

            # Update internal state
            self.daily_pnl += realized_pnl

            # Send to Recorder
            data = {
                "timestamp": ts,
                "instrument_id": instr_id,
                "side": side,
                "price": price,
                "quantity": qty,
                "realized_pnl": realized_pnl
            }
            RECORDER_QUEUE.put_nowait(("strategy_trade", data))

        except Exception as e:
            self.log.error(f"Failed to record trade: {e}")

    def _check_daily_loss(self) -> bool:
        """
        Check if daily realized loss exceeds limit (using in-memory state).
        Returns True if trading should stop.
        """
        if self.daily_pnl <= -self.config.daily_loss_limit_usdc:
            self.log.error(
                f"DAILY LOSS LIMIT REACHED: {self.daily_pnl:.2f} USDC "
                f"(Limit: -{self.config.daily_loss_limit_usdc}). Stopping new entries."
            )
            return True
        return False

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._check_sl_tp(tick)

    def _check_sl_tp(self, tick: QuoteTick) -> None:
        position = self.cache.position(tick.instrument_id)
        if not position or position.quantity == 0:
            return

        if self.cache.orders_open(tick.instrument_id):
            return

        if tick.bid_price.as_double() <= 0:
            return

        entry_price = self.local_entry_prices.get(tick.instrument_id.value, 0.0)
        if entry_price <= 0:
            entry_price = position.avg_px_open.as_double()

        if entry_price <= 0:
            return

        exit_price = tick.bid_price.as_double()
        if exit_price <= 0:
            return

        pnl_pct = (exit_price - entry_price) / entry_price

        if pnl_pct <= -self.config.stop_loss_pct:
            reason = f"Stop Loss triggered: PnL {pnl_pct:.2%} (Price: {exit_price:.4f}, Entry: {entry_price:.4f})"
            self.log.info(reason)
            self._close_position(position.instrument_id, reason)

        elif pnl_pct >= self.config.take_profit_pct:
            reason = f"Take Profit triggered: PnL {pnl_pct:.2%} (Price: {exit_price:.4f}, Entry: {entry_price:.4f})"
            self.log.info(reason)
            self._close_position(position.instrument_id, reason)

    def evaluate_markets(self, event_time: Optional[int] = None) -> None:
        self.log.info("Starting market evaluation...")
        self.analyzed_markets.clear()

        markets: Dict[str, List[Instrument]] = {}

        for instrument in self.cache.instruments():
            if not isinstance(instrument.info, dict):
                continue

            question = instrument.info.get("question")
            if not question:
                continue

            if question not in markets:
                markets[question] = []
            markets[question].append(instrument)

        self.log.info(f"Evaluating {len(markets)} markets.")

        for question, instruments in markets.items():
            asyncio.create_task(self._process_market_async(question, instruments))

    async def _process_market_async(self, question: str, instruments: List[Instrument]) -> None:
        if question in self.analyzed_markets:
            return
        self.analyzed_markets.add(question)

        description = str(instruments[0].info.get("description", ""))
        available_outcomes: List[str] = []
        prices: Dict[str, float] = {}

        for instr in instruments:
            outcome_val = instr.info.get("outcome") or instr.outcome
            outcome = str(outcome_val) if outcome_val else ""
            available_outcomes.append(outcome)

            quote = self.cache.quote(instr.id)
            if quote:
                price = (quote.bid_price.as_double() + quote.ask_price.as_double()) / 2
                if price == 0:
                    trade = self.cache.trade(instr.id)
                    price = trade.price.as_double() if trade else 0.5
            else:
                price = 0.5

            prices[outcome] = price

        self.log.info(f"Analyzing market: {question}")
        analysis = await self.gemini.analyze_market(
            question=question,
            description=description,
            prices=prices,
            available_outcomes=available_outcomes,
        )

        self._apply_analysis(question, instruments, analysis, available_outcomes)

    def _apply_analysis(
        self,
        question: str,
        instruments: List[Instrument],
        analysis: Dict[str, Any],
        available_outcomes: List[str],
    ) -> None:
        mode_prefix = "[PAPER] " if self.config.trading_mode == "paper" else ""
        self.notifier.send_analysis_update(f"{mode_prefix}{question}", analysis)

        action = analysis.get("action")
        target_outcome = str(analysis.get("target_outcome", ""))
        confidence = float(analysis.get("confidence", 0.0))

        if action == "buy" and confidence > 0.7:
            target_outcome_clean = target_outcome.strip().lower()

            target_instr = next(
                (i for i in instruments if str(i.info.get("outcome") or i.outcome).strip().lower() == target_outcome_clean),
                None,
            )

            if not target_instr:
                self.log.warning(
                    f"Could not map target outcome '{target_outcome}' to available outcomes {available_outcomes} "
                    "(Strict Match)"
                )
                return

            if target_instr:
                self._execute_buy(target_instr, str(analysis.get("reasoning", "")))

        elif action == "sell":
            reason = str(analysis.get("reasoning", "AI Sell Signal"))
            for instr in instruments:
                self._close_position(instr.id, reason)

    def _execute_buy(self, instrument: Instrument, reason: str) -> None:
        if self._check_daily_loss():
            return

        if self.cache.orders_open(instrument.id):
            self.log.info(f"Open orders exist for {instrument.id}, skipping buy.")
            return

        position = self.cache.position(instrument.id)
        if position and position.quantity > 0:
            self.log.info(f"Already holding position for {instrument.id}, skipping buy.")
            return

        quote = self.cache.quote(instrument.id)
        if not quote:
            self.log.warning(f"No quote for {instrument.id}, cannot buy.")
            return

        tick_size = instrument.price_increment.as_double()
        slippage = tick_size * self.config.risk_slippage_tolerance_ticks
        limit_price = quote.ask_price.as_double() + slippage

        if limit_price <= 0 or limit_price >= 1.0:
            self.log.warning(f"Invalid limit price {limit_price} for {instrument.id}")
            return

        risk_usdc = self.config.risk_max_position_size_usdc
        quantity_float = risk_usdc / limit_price

        try:
            qty = instrument.make_qty(quantity_float)
            price = instrument.make_price(limit_price)
        except Exception as e:
            self.log.error(f"Failed to create quantity/price: {e}")
            return

        order = self.order_factory.limit(
            instrument_id=instrument.id,
            order_side=OrderSide.BUY,
            quantity=qty,
            price=price,
            time_in_force=TimeInForce.GTC,
        )

        self.submit_order(order)
        self.log.info(f"Submitted BUY order for {instrument.id}: {qty} @ {price}")

        mode_prefix = "[PAPER] " if self.config.trading_mode == "paper" else ""
        self.notifier.send_trade_update(f"{mode_prefix}BUY", str(instrument.id), float(price), float(qty), reason)

    def _close_position(self, instrument_id: Any, reason: str) -> None:
        position = self.cache.position(instrument_id)
        if not position or position.quantity == 0:
            return

        self.close_position(instrument_id)
        self.log.info(f"Closed position for {instrument_id} due to: {reason}")

        self.notifier.send_trade_update("SELL", str(instrument_id), 0.0, float(position.quantity), reason)

    def on_bar(self, bar: Bar) -> None:
        pass
