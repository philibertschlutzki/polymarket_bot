import asyncio
import difflib
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

from src.intelligence.gemini import GeminiClient
from src.notifications import TelegramNotifier


class GeminiSentimentConfig(StrategyConfig, frozen=True):
    risk_max_position_size_usdc: float = 50.0
    risk_slippage_tolerance_ticks: int = 2
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_temperature: float = 0.1
    analysis_interval_hours: int = 24
    stop_loss_pct: float = 0.15
    take_profit_pct: float = 0.30
    trading_mode: str = "paper"


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

        self.analyzed_markets: Set[str] = set()  # Track analyzed questions to avoid duplicate calls per cycle

    def on_start(self) -> None:
        """
        Actions to be performed on strategy start.
        """
        self.log.info(f"GeminiSentimentStrategy started in {self.config.trading_mode.upper()} mode.")
        mode_prefix = "[PAPER] " if self.config.trading_mode == "paper" else ""
        self.notifier.send_message(f"{mode_prefix}🚀 Bot V2 Started. Strategy: Gemini Sentiment Analysis.")

        # Subscribe to data for all registered instruments
        for instrument in self.cache.instruments():
            self.subscribe_quote_ticks(instrument.id)
            self.log.info(f"Subscribed to {instrument.id}")

        # Schedule periodic analysis
        self.clock.schedule(
            self.evaluate_markets,
            interval=timedelta(hours=self.config.analysis_interval_hours),
        )

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """
        Monitor prices for Stop-Loss and Take-Profit.
        """
        self._check_sl_tp(tick)

    def _check_sl_tp(self, tick: QuoteTick) -> None:
        """
        Explicit Stop-Loss and Take-Profit Logic.
        """
        position = self.cache.position(tick.instrument_id)
        if not position or position.quantity == 0:
            return

        # Avoid multiple close orders
        if self.cache.orders_open(tick.instrument_id):
            return

        # Calculate current mid price
        mid_price = (tick.bid_price.as_double() + tick.ask_price.as_double()) / 2.0
        if mid_price <= 0:
            return

        # Calculate PnL percentage
        # avg_px_open is the average entry price
        entry_price = position.avg_px_open.as_double()
        if entry_price <= 0:
            return

        # Use Bid Price for Long Exit (Conservative PnL)
        exit_price = tick.bid_price.as_double()
        if exit_price <= 0:
            return

        pnl_pct = (exit_price - entry_price) / entry_price

        # Check Stop Loss
        if pnl_pct <= -self.config.stop_loss_pct:
            reason = f"Stop Loss triggered: PnL {pnl_pct:.2%} (Price: {exit_price:.4f}, Entry: {entry_price:.4f})"
            self.log.info(reason)
            self._close_position(position.instrument_id, reason)

        # Check Take Profit
        elif pnl_pct >= self.config.take_profit_pct:
            reason = f"Take Profit triggered: PnL {pnl_pct:.2%} (Price: {exit_price:.4f}, Entry: {entry_price:.4f})"
            self.log.info(reason)
            self._close_position(position.instrument_id, reason)

    def evaluate_markets(self, event_time: Optional[int] = None) -> None:
        """
        Daily market re-evaluation logic.
        """
        self.log.info("Starting market evaluation...")
        self.analyzed_markets.clear()

        # Group instruments by market (question)
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
            # Schedule async task for analysis
            asyncio.create_task(self._process_market_async(question, instruments))

    async def _process_market_async(self, question: str, instruments: List[Instrument]) -> None:
        """
        Process a single market asynchronously.
        """
        if question in self.analyzed_markets:
            return
        self.analyzed_markets.add(question)

        # Gather market data
        description = str(instruments[0].info.get("description", ""))
        available_outcomes: List[str] = []
        prices: Dict[str, float] = {}

        for instr in instruments:
            # Ensure outcome is a string for difflib
            outcome_val = instr.info.get("outcome") or instr.outcome
            outcome = str(outcome_val) if outcome_val else ""
            available_outcomes.append(outcome)

            # Get latest price (mid or last)
            quote = self.cache.quote(instr.id)
            if quote:
                price = (quote.bid_price.as_double() + quote.ask_price.as_double()) / 2
                if price == 0:
                    trade = self.cache.trade(instr.id)
                    price = trade.price.as_double() if trade else 0.5
            else:
                price = 0.5  # Default if no data

            prices[outcome] = price

        # Call Gemini (Async)
        self.log.info(f"Analyzing market: {question}")
        analysis = await self.gemini.analyze_market(
            question=question,
            description=description,
            prices=prices,
            available_outcomes=available_outcomes,
        )

        # Apply results
        self._apply_analysis(question, instruments, analysis, available_outcomes)

    def _apply_analysis(
        self,
        question: str,
        instruments: List[Instrument],
        analysis: Dict[str, Any],
        available_outcomes: List[str],
    ) -> None:
        """
        Apply the analysis result (Trading Logic).
        """
        # Send update with mode prefix
        mode_prefix = "[PAPER] " if self.config.trading_mode == "paper" else ""
        # We might need to modify notifier to accept prefix or just prepend to question
        # Assuming send_analysis_update handles strings, we can prepend
        self.notifier.send_analysis_update(f"{mode_prefix}{question}", analysis)

        # Action Logic
        action = analysis.get("action")
        target_outcome = str(analysis.get("target_outcome", ""))
        confidence = float(analysis.get("confidence", 0.0))

        if action == "buy" and confidence > 0.7:
            # Find matching instrument
            matches = difflib.get_close_matches(target_outcome, available_outcomes, n=1, cutoff=0.6)
            if not matches:
                self.log.warning(f"Could not map target outcome '{target_outcome}' to available outcomes {available_outcomes}")
                return

            matched_outcome = matches[0]

            # Find instrument for this outcome
            target_instr = next(
                (i for i in instruments if (i.info.get("outcome") == matched_outcome or i.outcome == matched_outcome)),
                None,
            )

            if target_instr:
                self._execute_buy(target_instr, str(analysis.get("reasoning", "")))

        elif action == "sell":
            # Exit all positions for this market
            reason = str(analysis.get("reasoning", "AI Sell Signal"))
            for instr in instruments:
                self._close_position(instr.id, reason)

    def _execute_buy(self, instrument: Instrument, reason: str) -> None:
        """
        Execute a buy order with risk checks.
        """
        # Check if already working an order
        if self.cache.orders_open(instrument.id):
            self.log.info(f"Open orders exist for {instrument.id}, skipping buy.")
            return

        # Check current position
        position = self.cache.position(instrument.id)
        if position and position.quantity > 0:
            self.log.info(f"Already holding position for {instrument.id}, skipping buy.")
            return

        # Calculate quantity based on risk (USDC)
        # Price: Aggressive (Ask + slippage)
        quote = self.cache.quote(instrument.id)
        if not quote:
            self.log.warning(f"No quote for {instrument.id}, cannot buy.")
            return

        # Aggressive price: Best Ask + X ticks
        tick_size = instrument.price_increment.as_double()
        slippage = tick_size * self.config.risk_slippage_tolerance_ticks
        limit_price = quote.ask_price.as_double() + slippage

        if limit_price <= 0 or limit_price >= 1.0:
            self.log.warning(f"Invalid limit price {limit_price} for {instrument.id}")
            return

        # Quantity = Risk / Price
        risk_usdc = self.config.risk_max_position_size_usdc
        quantity_float = risk_usdc / limit_price

        # Use instrument to make proper Quantity and Price objects
        try:
            qty = instrument.make_qty(quantity_float)
            price = instrument.make_price(limit_price)
        except Exception as e:
            self.log.error(f"Failed to create quantity/price: {e}")
            return

        # Build Order
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
        """
        Close a position if exists.
        Renamed parameter to instrument_id for internal consistency if passed ID directly,
        but helper expects ID.
        """
        # Ensure instrument_id is properly typed if needed, usually it's a string or ID object
        position = self.cache.position(instrument_id)
        if not position or position.quantity == 0:
            return

        self.close_position(instrument_id)
        self.log.info(f"Closed position for {instrument_id} due to: {reason}")

        # Price unknown at submission, using 0.0 for notification
        self.notifier.send_trade_update("SELL", str(instrument_id), 0.0, float(position.quantity), reason)

    def on_bar(self, bar: Bar) -> None:
        # We use timer for evaluation, but we process bars/ticks for data updates
        pass
