# Polymarket AI Trader - Source Code

This directory contains the core logic of the Polymarket AI Trader. The project is structured to enforce a strict separation of concerns between data, execution, and strategy layers.

## 📂 Directory Structure

### `data/`
Responsible for data persistence and retrieval.
*   **`recorder.py`**: A custom Nautilus Strategy that asynchronously records `QuoteTick` and `TradeTick` data to a local SQLite database using Write-Ahead Logging (WAL) for performance.

### `intelligence/`
Handles interactions with Large Language Models (LLMs).
*   **`gemini.py`**: A wrapper for the Google Gemini 2.0 API. It constructs prompts with market context (prices, outcomes) and parses structured JSON responses (`buy`/`sell` signals with reasoning).

### `scanner/`
Manages market discovery via the Polymarket Gamma API.
*   **`polymarket.py`**: Fetches market data, applies filters (volume, spread, expiration), and converts raw API responses into Nautilus `Instrument` objects.
*   **`service.py`**: A periodic service that runs the scanner at configurable intervals to find new opportunities.

### `strategies/`
Contains the trading logic implemented as Nautilus Trader strategies.
*   **`sentiment.py`**: The main strategy. Subscribes to market data, triggers AI analysis based on price movements or time intervals, and executes orders based on LLM signals.

### `utils/`
Helper functions and utilities.
*   **`logging.py`**: Configures the application's logging system, including rotating file handlers and asynchronous Telegram error notifications.

### `main.py`
The application entry point.
*   Loads configuration (`config.toml`).
*   Initializes logging.
*   Sets up the Nautilus `TradingNode`.
*   Runs the initial market scan.
*   Registers strategies and starts the event loop.

## 🏗 Key Design Patterns

1.  **Event-Driven:** All trading logic responds to market events (ticks, bars) or timer events.
2.  **Asynchronous I/O:** Database writes and API calls are offloaded to `asyncio` tasks or thread executors to prevent blocking the main trading loop.
3.  **Strict Typing:** The codebase enforces strict Python typing to catch errors early.
4.  **Dependency Injection:** Configuration objects are passed into components rather than being hardcoded.
