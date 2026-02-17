import asyncio
import logging
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from nautilus_trader.adapters.polymarket import (  # type: ignore
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)
from nautilus_trader.config import (
    LiveDataClientConfig,
    LiveExecClientConfig,
    LiveExecEngineConfig,
    LoggingConfig,
    OrderEmulatorConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.instruments import Instrument

from src.data.recorder import RecorderConfig, RecorderStrategy
from src.scanner.polymarket import PolymarketScanner
from src.scanner.service import PeriodicScannerService
from src.strategies.sentiment import GeminiSentimentConfig, GeminiSentimentStrategy
from src.utils.logging import setup_logging

# Load env
load_dotenv()

logger = logging.getLogger("main")


def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.toml.
    """
    default_path = Path(__file__).parent.parent / "config" / "config.toml"
    config_file_env = os.getenv("CONFIG_FILE")
    config_path = Path(config_file_env) if config_file_env else default_path

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def setup_node(config: Dict[str, Any]) -> TradingNode:
    """
    Configure and build the Nautilus TradingNode.
    """
    private_key: Optional[str] = os.getenv("POLYGON_PRIVATE_KEY")
    funder: Optional[str] = os.getenv("POLYGON_ADDRESS")
    api_key: Optional[str] = os.getenv("POLYMARKET_API_KEY")
    api_secret: Optional[str] = os.getenv("POLYMARKET_API_SECRET")
    passphrase: Optional[str] = os.getenv("POLYMARKET_PASSPHRASE")

    # Determine Trading Mode
    trading_config = config.get("trading", {})
    trading_mode: str = trading_config.get("mode", "paper").lower()
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

    data_clients: Dict[str, LiveDataClientConfig] = {"POLYMARKET": polymarket_data_config}
    exec_clients: Dict[str, LiveExecClientConfig] = {}
    emulator_config: Optional[OrderEmulatorConfig] = None

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
    """
    Run the trading node loop.
    """
    logger.info("Starting Trading Node...")
    try:
        node.run()
    except KeyboardInterrupt:
        logger.info("Node stopped by user.")
    except Exception as e:
        logger.error(f"Node error: {e}")
    finally:
        # Graceful shutdown
        try:
            node.stop()
            node.dispose()
        except Exception as e:
            logger.error(f"Error disposing node: {e}")

        try:
            scanner_service.stop()
        except Exception as e:
            logger.error(f"Error stopping scanner: {e}")


def setup_strategies(node: TradingNode, config: Dict[str, Any]) -> None:
    """
    Configure and add strategies to the trading node.
    """
    trading_mode = config.get("trading", {}).get("mode", "paper").lower()
    gemini_config = config.get("gemini", {})
    risk_config = config.get("risk", {})

    strat_config = GeminiSentimentConfig(
        risk_max_position_size_usdc=float(risk_config.get("max_position_size_usdc", 50.0)),
        risk_slippage_tolerance_ticks=int(risk_config.get("slippage_tolerance_ticks", 2)),
        gemini_model=gemini_config.get("model", "gemini-2.0-flash-exp"),
        gemini_temperature=float(gemini_config.get("temperature", 0.1)),
        trading_mode=trading_mode,
        daily_loss_limit_usdc=float(os.getenv("DAILY_LOSS_LIMIT_USDC", 100.0)),
    )

    strategy = GeminiSentimentStrategy(config=strat_config)
    node.trader.add_strategy(strategy)

    logger.info("Adding SQLite Data Recorder...")
    recorder_config = RecorderConfig(
        batch_size=100,
        flush_interval_seconds=5.0,
    )
    recorder = RecorderStrategy(config=recorder_config)
    node.trader.add_strategy(recorder)


def setup_initial_instruments(loop: asyncio.AbstractEventLoop, config: Dict[str, Any], node: TradingNode) -> None:
    """
    Scan for initial instruments and add them to the provider.
    """
    logger.info("Running Market Scanner (Initial)...")
    scanner = PolymarketScanner(config)

    instruments: List[Instrument] = []
    try:
        scan_result = loop.run_until_complete(scanner.scan())
        if scan_result:
            instruments = scan_result
    except Exception as e:
        logger.error(f"Initial scan failed: {e}")

    if not instruments:
        logger.warning("No instruments found by scanner. Starting anyway (will retry in periodic scan).")
    else:
        logger.info(f"Scanner found {len(instruments)} instruments. Registering...")

    # Type casting to access instrument_provider if not directly available on type hint
    instrument_provider = getattr(node, "instrument_provider", None)

    if not instrument_provider:
        logger.critical("No InstrumentProvider found on TradingNode. Exiting.")
        sys.exit(1)

    for instrument in instruments:
        instrument_provider.add(instrument)


def main() -> None:
    """
    Application Entry Point.
    """
    try:
        config = load_config()
    except Exception as e:
        print(f"Failed to load config: {e}")
        return

    setup_logging(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        node = setup_node(config)

        setup_initial_instruments(loop, config, node)

        setup_strategies(node, config)

        scanner_interval = int(config.get("scanner", {}).get("interval_hours", 1))

        scanner_service = PeriodicScannerService(
            scanner=PolymarketScanner(config),
            instrument_provider=getattr(node, "instrument_provider", None),
            interval_hours=scanner_interval,
        )

        loop.create_task(scanner_service.run())

        run_node(node, scanner_service, loop)

    except Exception as e:
        logger.critical(f"Fatal error in main: {e}")
    finally:
        if not loop.is_closed():
            try:
                # Cancel pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Run loop to clear tasks
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()
            except Exception as e:
                print(f"Error closing loop: {e}")


if __name__ == "__main__":
    main()
