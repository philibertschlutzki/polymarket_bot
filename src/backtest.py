import logging
import sqlite3
from pathlib import Path
from typing import Any, List, Set

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity

from src.data.loaders import SQLiteDataLoader
from src.strategies.sentiment import GeminiSentimentConfig, GeminiSentimentStrategy

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backtest")


def get_instrument_ids(db_path: str) -> Set[str]:
    """Identify Instruments from DB."""
    instrument_ids = set()
    try:
        with sqlite3.connect(db_path) as conn:
            # Check for quotes table
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quotes'")
            if cursor.fetchone():
                cursor = conn.execute("SELECT DISTINCT instrument_id FROM quotes")
                for row in cursor:
                    instrument_ids.add(row[0])

            # Check for trades table
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if cursor.fetchone():
                cursor = conn.execute("SELECT DISTINCT instrument_id FROM trades")
                for row in cursor:
                    instrument_ids.add(row[0])
    except Exception as e:
        logger.error(f"Failed to read DB: {e}")
        return set()

    return instrument_ids


def create_mock_instrument(i_str: str) -> Instrument:
    """Create a mock instrument with metadata."""
    instr_id = InstrumentId.from_str(i_str)

    # Use generic Instrument
    # Assuming standard fields are sufficient for the strategy
    instrument = Instrument(
        instrument_id=instr_id,
        raw_symbol=Symbol(i_str),
        venue=Venue("POLYMARKET"),
        price_precision=4,
        size_precision=1,
        price_increment=Price.from_str("0.0001"),
        size_increment=Quantity.from_str("0.1"),
        lot_size=Quantity.from_str("0.1"),
        max_quantity=Quantity.from_str("10000"),
        min_quantity=Quantity.from_str("0.1"),
        base_currency=USD,
        quote_currency=USD,
        product_type="BINARY",
    )

    # Inject metadata for Gemini Strategy
    instrument.info = {
        "question": f"Question for {i_str}",
        "outcome": "Yes",
        "description": f"Mock Description for {i_str}",
    }
    return instrument


def load_data(
    engine: BacktestEngine,
    instrument_ids: Set[str],
    db_path: str,
) -> List[Any]:
    """Load data and register instruments."""
    loader = SQLiteDataLoader(db_path=db_path)
    ticks: List[Any] = []

    for i_str in instrument_ids:
        instrument = create_mock_instrument(i_str)
        engine.add_instrument(instrument)

        # Load and collect ticks
        q_ticks = loader.load_quotes(i_str)
        t_ticks = loader.load_trades(i_str)

        if q_ticks:
            ticks.extend(q_ticks)
        if t_ticks:
            ticks.extend(t_ticks)

    return ticks


def main() -> None:
    db_path = "src/data/market_data.db"
    if not Path(db_path).exists():
        logger.error(f"Database not found at {db_path}. Please copy it from VPS.")
        return

    # 1. Configure Backtest Engine directly
    engine_config = BacktestEngineConfig(
        trader_id="BACKTESTER",
        risk_engine=RiskEngineConfig(bypass=True),
        logging=LoggingConfig(log_level="INFO", log_level_file="INFO"),
    )

    engine = BacktestEngine(config=engine_config)

    # 2. Identify Instruments from DB
    instrument_ids = get_instrument_ids(db_path)
    logger.info(f"Found {len(instrument_ids)} instruments in DB.")

    # 3. Load Data & Create Mock Instruments
    ticks = load_data(engine, instrument_ids, db_path)

    if not ticks:
        logger.warning("No data found in DB.")
        return

    # Sort all ticks by timestamp
    ticks.sort(key=lambda x: x.ts_event)

    logger.info(f"Loaded {len(ticks)} ticks. Adding to engine...")
    for tick in ticks:
        engine.add_data(tick)

    # 4. Add Strategy
    strat_config = GeminiSentimentConfig(
        trading_mode="backtest",
        gemini_model="gemini-2.0-flash",
        analysis_interval_hours=24,  # Run daily analysis
    )

    strategy = GeminiSentimentStrategy(config=strat_config)
    engine.add_strategy(strategy)

    # 5. Run Backtest
    logger.info("Starting Backtest Run...")
    engine.run()

    logger.info("Backtest Complete.")

    # Print simple results
    account = engine.portfolio.account(USD)
    if account:
        logger.info(f"Final Account Balance: {account.balance_total()}")
    else:
        logger.info("No USD account found.")


if __name__ == "__main__":
    main()
