import asyncio
import logging
import os
import tomllib
from typing import Any, cast

from dotenv import load_dotenv
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)
from nautilus_trader.config import (
    LiveExecEngineConfig,
    LiveExecClientConfig,
    LiveDataClientConfig,
    LoggingConfig,
    TradingNodeConfig,
    OrderEmulatorConfig,
)
from nautilus_trader.live.node import TradingNode

from src.data.recorder import RecorderConfig, RecorderStrategy
from src.scanner.polymarket import PolymarketScanner
from src.scanner.service import PeriodicScannerService
from src.strategies.sentiment import GeminiSentimentConfig, GeminiSentimentStrategy

# Load env
load_dotenv()

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("main")


def load_config() -> dict[str, Any]:
    with open("config/config.toml", "rb") as f:
        return tomllib.load(f)


def setup_node(config: dict[str, Any]) -> TradingNode:
    private_key = os.getenv("POLYGON_PRIVATE_KEY")
    funder = os.getenv("POLYGON_ADDRESS")
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")

    # Determine Trading Mode
    trading_mode = config.get("trading", {}).get("mode", "paper").lower()
    logger.info(f"Setting up Trading Node in {trading_mode.upper()} mode.")

    if trading_mode == "live" and not private_key:
        logger.warning("POLYGON_PRIVATE_KEY not set. Execution might fail.")

    polymarket_data_config = PolymarketDataClientConfig(
        private_key=private_key,
        funder=funder,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )

    data_clients: dict[str, LiveDataClientConfig] = {"POLYMARKET": polymarket_data_config}
    exec_clients: dict[str, LiveExecClientConfig] = {}
    emulator_config = None

    if trading_mode == "live":
        polymarket_exec_config = PolymarketExecClientConfig(
            private_key=private_key,
            funder=funder,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
        )
        exec_clients = {"POLYMARKET": polymarket_exec_config}
    else:
        # Paper Mode: Use Order Emulator
        logger.info("Using internal Order Emulator for execution simulation.")
        emulator_config = OrderEmulatorConfig()

    node = TradingNode(
        config=TradingNodeConfig(
            trader_id="POLYMARKET-BOT-V2",
            logging=LoggingConfig(log_level="INFO"),
            exec_engine=LiveExecEngineConfig(
                reconciliation=True,
                reconciliation_lookback_mins=10,
            ),
            data_clients=data_clients,
            exec_clients=exec_clients,
            emulator=emulator_config,
        )
    )

    node.add_data_client_factory("POLYMARKET", PolymarketLiveDataClientFactory)

    if trading_mode == "live":
        node.add_exec_client_factory("POLYMARKET", PolymarketLiveExecClientFactory)

    node.build()
    return node


def run_node(
    node: TradingNode,
    scanner_service: PeriodicScannerService,
    loop: asyncio.AbstractEventLoop,
) -> None:
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
        scanner_service.stop()
        loop.close()


def main() -> None:
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    node = setup_node(config)

    logger.info("Running Market Scanner (Initial)...")
    scanner = PolymarketScanner(config)

    try:
        instruments = loop.run_until_complete(scanner.scan())
    except Exception as e:
        logger.error(f"Initial scan failed: {e}")
        instruments = []

    if not instruments:
        logger.warning(
            "No instruments found by scanner. Starting anyway (will retry in periodic scan)."
        )
    else:
        logger.info(f"Scanner found {len(instruments)} instruments. Registering...")

    for instrument in instruments:
        cast(Any, node).instrument_provider.add(instrument)

    trading_mode = config.get("trading", {}).get("mode", "paper").lower()
    strat_config = GeminiSentimentConfig(
        risk_max_position_size_usdc=float(config["risk"]["max_position_size_usdc"]),
        risk_slippage_tolerance_ticks=int(config["risk"]["slippage_tolerance_ticks"]),
        gemini_model=config["gemini"]["model"],
        gemini_temperature=config["gemini"]["temperature"],
        trading_mode=trading_mode,
    )

    strategy = GeminiSentimentStrategy(config=strat_config)
    node.trader.add_strategy(strategy)

    logger.info("Adding SQLite Data Recorder...")
    recorder_config = RecorderConfig(
        db_path="src/data/market_data.db",
        batch_size=100,
        flush_interval_seconds=5.0,
    )
    recorder = RecorderStrategy(config=recorder_config)
    node.trader.add_strategy(recorder)

    scanner_interval = int(config.get("scanner", {}).get("interval_hours", 1))
    scanner_service = PeriodicScannerService(
        scanner=scanner,
        instrument_provider=cast(Any, node).instrument_provider,
        interval_hours=scanner_interval,
    )

    loop.create_task(scanner_service.run())

    run_node(node, scanner_service, loop)


if __name__ == "__main__":
    main()
