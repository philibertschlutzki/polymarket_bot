import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId

from src.strategies.sentiment import GeminiSentimentConfig, GeminiSentimentStrategy


class StrategyWrapper(GeminiSentimentStrategy):
    def __init__(self, config: GeminiSentimentConfig):
        # We try to initialize super, but ignore errors if Actor setup fails
        try:
            super().__init__(config)
        except Exception:
            pass

        self._config = config
        self.gemini = MagicMock()
        self.notifier = MagicMock()
        self.tasks = set()
        self.analyzed_markets = set()

        # Manually initialize attributes that might have been skipped if super().__init__ failed
        self.local_entry_prices = {}
        self.subscribed_instruments = set()
        self.daily_pnl = 0.0
        self.db_path = "src/data/market_data.db"
        self.semaphore = asyncio.Semaphore(3)

        self._mock_log = MagicMock()
        self._mock_cache = MagicMock()
        self._mock_order_factory = MagicMock()
        self._mock_submit_order = MagicMock()
        self._mock_close_position = MagicMock()

    @property
    def log(self):
        return self._mock_log

    @property
    def cache(self):
        return self._mock_cache

    @property
    def order_factory(self):
        return self._mock_order_factory

    def submit_order(self, order):
        self._mock_submit_order(order)

    def close_position(self, instrument_id):
        self._mock_close_position(instrument_id)


@pytest.fixture
def strat_config(config: Dict[str, Any]) -> GeminiSentimentConfig:
    return GeminiSentimentConfig(
        risk_max_position_size_usdc=50.0,
        risk_slippage_tolerance_ticks=2,
        gemini_model="test-model",
        gemini_temperature=0.0,
        trading_mode="paper",
        stop_loss_pct=0.15,
        take_profit_pct=0.30,
    )


@pytest.fixture
def strategy(strat_config: GeminiSentimentConfig) -> StrategyWrapper:
    strat = StrategyWrapper(strat_config)
    strat.gemini.analyze_market = AsyncMock()  # type: ignore
    return strat


def test_check_sl_tp_stop_loss(strategy: StrategyWrapper) -> None:
    # Setup
    instrument_id = InstrumentId.from_str("123-Yes.POLYMARKET")

    # Position: Entry 0.50, Size 100
    position = MagicMock()
    position.instrument_id = instrument_id
    position.quantity = 100.0
    position.avg_px_open.as_double.return_value = 0.50
    strategy.cache.position.return_value = position
    strategy.cache.orders_open.return_value = False  # No open orders

    # Tick: Price 0.40 (20% loss > 15% SL)
    tick = MagicMock(spec=QuoteTick)
    tick.instrument_id = instrument_id
    tick.bid_price.as_double.return_value = 0.39
    tick.ask_price.as_double.return_value = 0.41
    # Mid = 0.40

    # Execute
    strategy._check_sl_tp(tick)

    # Assert
    strategy._mock_close_position.assert_called_once_with(instrument_id)
    strategy.notifier.send_trade_update.assert_called_once()
    assert "SELL" in strategy.notifier.send_trade_update.call_args[0]


def test_check_sl_tp_take_profit(strategy: StrategyWrapper) -> None:
    # Setup
    instrument_id = InstrumentId.from_str("123-Yes.POLYMARKET")

    # Position: Entry 0.50
    position = MagicMock()
    position.instrument_id = instrument_id
    position.quantity = 100.0
    position.avg_px_open.as_double.return_value = 0.50
    strategy.cache.position.return_value = position
    strategy.cache.orders_open.return_value = False

    # Tick: Price 0.70 (40% gain > 30% TP)
    tick = MagicMock(spec=QuoteTick)
    tick.instrument_id = instrument_id
    tick.bid_price.as_double.return_value = 0.69
    tick.ask_price.as_double.return_value = 0.71
    # Mid = 0.70

    # Execute
    strategy._check_sl_tp(tick)

    # Assert
    strategy._mock_close_position.assert_called_once_with(instrument_id)
    strategy.notifier.send_trade_update.assert_called_once()


@pytest.mark.asyncio
async def test_process_market_async_buy_signal(strategy: StrategyWrapper) -> None:
    # Setup
    question = "Will it rain?"
    instrument = MagicMock()
    instrument.id = InstrumentId.from_str("123-Yes.POLYMARKET")
    instrument.info = {"outcome": "Yes", "description": "Rain?"}
    instrument.outcome = "Yes"
    instrument.price_increment.as_double.return_value = 0.01
    # instrument.make_qty/price mocks
    instrument.make_qty.return_value = 100.0
    instrument.make_price.return_value = 0.53

    instruments = [instrument]

    # Mock Cache for price
    quote = MagicMock()
    quote.bid_price.as_double.return_value = 0.49
    quote.ask_price.as_double.return_value = 0.51
    strategy.cache.quote.return_value = quote
    strategy.cache.orders_open.return_value = False
    strategy.cache.position.return_value = None

    # Mock Gemini Analysis
    strategy.gemini.analyze_market.return_value = {  # type: ignore
        "action": "buy",
        "target_outcome": "Yes",
        "confidence": 0.8,
        "reasoning": "High chance of rain",
    }

    # Execute
    await strategy._process_market_async(question, instruments)

    # Assert
    strategy.gemini.analyze_market.assert_called_once()
    strategy._mock_submit_order.assert_called_once()
    strategy.notifier.send_analysis_update.assert_called_once()
    strategy.notifier.send_trade_update.assert_called_once()


@pytest.mark.asyncio
async def test_process_market_async_sell_signal(strategy: StrategyWrapper) -> None:
    # Setup
    question = "Will it rain?"
    instrument = MagicMock()
    instrument.id = InstrumentId.from_str("123-Yes.POLYMARKET")
    instrument.info = {"outcome": "Yes"}

    instruments = [instrument]

    strategy.cache.quote.return_value = None
    strategy.cache.trade.return_value = None

    # Mock position exists
    position = MagicMock()
    position.quantity = 100
    strategy.cache.position.return_value = position

    # Mock Gemini Analysis
    strategy.gemini.analyze_market.return_value = {"action": "sell", "reasoning": "Data changed"}  # type: ignore

    # Execute
    await strategy._process_market_async(question, instruments)

    # Assert
    strategy._mock_close_position.assert_called_once_with(instrument.id)
    strategy.notifier.send_trade_update.assert_called_once()
