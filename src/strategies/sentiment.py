import difflib
from datetime import timedelta

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
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


class GeminiSentimentStrategy(Strategy):
    def __init__(self, config: GeminiSentimentConfig):
        super().__init__(config)
        self.config = config

        # Initialize components
        # We can pass specific config parts if needed, or just let them read env/defaults
        self.gemini = GeminiClient(
            config={
                "gemini": {
                    "model": self.config.gemini_model,
                    "temperature": self.config.gemini_temperature,
                }
            }
        )
        self.notifier = TelegramNotifier()

        self.analyzed_markets: set[str] = (
            set()
        )  # Track analyzed questions to avoid duplicate calls per cycle

    def on_start(self) -> None:
        """
        Actions to be performed on strategy start.
        """
        self.log.info("GeminiSentimentStrategy started.")
        self.notifier.send_message(
            "🚀 Bot V2 Started. Strategy: Gemini Sentiment Analysis."
        )

        # Subscribe to data for all registered instruments
        for instrument in self.cache.instruments():
            self.subscribe_quote_ticks(instrument.id)
            self.log.info(f"Subscribed to {instrument.id}")

        # Schedule periodic analysis
        # First run in 10 seconds to allow data to load
        self.clock.schedule(self.evaluate_markets, interval=timedelta(seconds=10))

        # Then schedule regular interval
        self.clock.schedule(
            self.evaluate_markets,
            interval=timedelta(hours=self.config.analysis_interval_hours),
        )

    def evaluate_markets(self, event_time=None) -> None:
        """
        Daily market re-evaluation logic.
        """
        self.log.info("Starting market evaluation...")
        self.analyzed_markets.clear()

        # Group instruments by market (question)
        # Instrument.info['question'] should be available from our scanner parsing
        markets: dict[str, list[Instrument]] = {}

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
            self._process_market(question, instruments)

    def _process_market(self, question: str, instruments: list[Instrument]) -> None:
        """
        Process a single market (group of outcomes).
        """
        if question in self.analyzed_markets:
            return
        self.analyzed_markets.add(question)

        # Gather market data
        description = instruments[0].info.get("description", "")
        available_outcomes = []
        prices = {}

        for instr in instruments:
            outcome = instr.info.get("outcome") or instr.outcome  # Fallback to property
            available_outcomes.append(outcome)

            # Get latest price (mid or last)
            # We need quote tick or bar
            # Check cache for quote
            quote = self.cache.quote(instr.id)
            if quote:
                # Use mid price if available, else last trade, else 0.5
                price = (quote.bid_price.as_double() + quote.ask_price.as_double()) / 2
                if price == 0:
                    # try last trade
                    trade = self.cache.trade(instr.id)
                    price = trade.price.as_double() if trade else 0.5
            else:
                price = 0.5  # Default if no data

            prices[outcome] = price

        # Call Gemini
        self.log.info(f"Analyzing market: {question}")
        analysis = self.gemini.analyze_market(
            question=question,
            description=description,
            prices=prices,
            available_outcomes=available_outcomes,
        )

        # Send update
        self.notifier.send_analysis_update(question, analysis)

        # Action Logic
        action = analysis.get("action")
        target_outcome = analysis.get("target_outcome")
        confidence = analysis.get("confidence", 0.0)

        if action == "buy" and confidence > 0.7:
            # Find matching instrument
            # Use fuzzy matching as requested
            matches = difflib.get_close_matches(
                target_outcome, available_outcomes, n=1, cutoff=0.6
            )
            if not matches:
                self.log.warning(
                    f"Could not map target outcome '{target_outcome}' to available outcomes {available_outcomes}"
                )
                return

            matched_outcome = matches[0]

            # Find instrument for this outcome
            target_instr = next(
                (
                    i
                    for i in instruments
                    if (
                        i.info.get("outcome") == matched_outcome
                        or i.outcome == matched_outcome
                    )
                ),
                None,
            )

            if target_instr:
                self._execute_buy(target_instr, analysis.get("reasoning", ""))

        elif action == "sell":
            # Exit all positions for this market
            for instr in instruments:
                self._close_position(instr, analysis.get("reasoning", ""))

    def _execute_buy(self, instrument: Instrument, reason: str) -> None:
        """
        Execute a buy order.
        """
        # Check current position
        position = self.cache.position(instrument.id)
        if position and position.quantity > 0:
            self.log.info(
                f"Already holding position for {instrument.id}, skipping buy."
            )
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
        # Ensure min order size
        # Max position size USDC
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
            time_in_force=TimeInForce.GTC,  # Good Till Cancel
        )

        self.submit_order(order)
        self.log.info(f"Submitted BUY order for {instrument.id}: {qty} @ {price}")
        self.notifier.send_trade_update(
            "BUY", str(instrument.id), float(price), float(qty), reason
        )

    def _close_position(self, instrument: Instrument, reason: str) -> None:
        """
        Close a position if exists.
        """
        position = self.cache.position(instrument.id)
        if not position or position.quantity == 0:
            return

        self.close_position(instrument.id)
        self.log.info(f"Closed position for {instrument.id}")
        # Price unknown at submission
        self.notifier.send_trade_update(
            "SELL", str(instrument.id), 0.0, float(position.quantity), reason
        )

    def on_bar(self, bar: Bar) -> None:
        # We use timer for evaluation, but we process bars for data updates
        pass
