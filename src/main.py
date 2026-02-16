import asyncio
import logging
import os
import tomllib

from dotenv import load_dotenv
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig, PolymarketExecClientConfig,
    PolymarketLiveDataClientFactory, PolymarketLiveExecClientFactory)
from nautilus_trader.config import (LiveExecEngineConfig, LoggingConfig,
                                    TradingNodeConfig)
from nautilus_trader.live.node import TradingNode

from src.scanner.polymarket import PolymarketScanner
from src.strategies.sentiment import (GeminiSentimentConfig,
                                      GeminiSentimentStrategy)

# Load env
load_dotenv()

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("main")


def load_config():
    with open("config/config.toml", "rb") as f:
        return tomllib.load(f)


def main():
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    # 2. Configure Polymarket Clients
    # Map Env Vars
    private_key = os.getenv("POLYGON_PRIVATE_KEY")
    funder = os.getenv("POLYGON_ADDRESS")
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")

    if not private_key:
        logger.warning("POLYGON_PRIVATE_KEY not set. Execution might fail.")

    # Client Configs
    polymarket_data_config = PolymarketDataClientConfig(
        private_key=private_key,
        funder=funder,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )

    polymarket_exec_config = PolymarketExecClientConfig(
        private_key=private_key,
        funder=funder,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )

    # 1. Initialize Node with Client Configs
    node = TradingNode(
        config=TradingNodeConfig(
            trader_id="POLYMARKET-BOT-V2",
            logging=LoggingConfig(log_level="INFO"),
            exec_engine=LiveExecEngineConfig(
                reconciliation=True,
                reconciliation_lookback_mins=10,
            ),
            data_clients={"POLYMARKET": polymarket_data_config},
            exec_clients={"POLYMARKET": polymarket_exec_config},
        )
    )

    # 2. Register Client Factories
    node.add_data_client_factory("POLYMARKET", PolymarketLiveDataClientFactory)
    node.add_exec_client_factory("POLYMARKET", PolymarketLiveExecClientFactory)

    # Initialize components
    node.build()

    # 3. Run Scanner
    logger.info("Running Market Scanner...")
    scanner = PolymarketScanner(config)

    instruments = asyncio.run(scanner.scan())

    if not instruments:
        logger.warning("No instruments found by scanner. Exiting.")
        return

    logger.info(f"Scanner found {len(instruments)} instruments. Registering...")

    # 4. Register Instruments
    for instrument in instruments:
        node.instrument_provider.add(instrument)

    # 5. Add Strategy
    strat_config = GeminiSentimentConfig(
        instrument_id=None,
        risk_max_position_size_usdc=float(config["risk"]["max_position_size_usdc"]),
        risk_slippage_tolerance_ticks=int(config["risk"]["slippage_tolerance_ticks"]),
        gemini_model=config["gemini"]["model"],
        gemini_temperature=config["gemini"]["temperature"],
    )

    strategy = GeminiSentimentStrategy(config=strat_config)
    node.trader.add_strategy(strategy)

    # 6. Run
    logger.info("Starting Trading Node...")
    try:
        node.run()
    except KeyboardInterrupt:
        logger.info("Node stopped by user.")
    except Exception as e:
        logger.error(f"Node error: {e}")
    finally:
        node.stop()
        node.dispose()


if __name__ == "__main__":
    main()
