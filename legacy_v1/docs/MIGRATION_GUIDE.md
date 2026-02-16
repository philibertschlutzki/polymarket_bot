# Migration Guide: v1.0 (Batch) to v2.0 (Continuous)

This guide covers upgrading the Polymarket Bot from the batch-processing architecture to the new continuous stream-processing system.

## Prerequisites

1.  **Backup Data**: Ensure you have a backup of `polymarket_bot.db`.
2.  **Stop Service**: Stop the currently running bot service.

## Installation Steps

1.  **Update Code**:
    ```bash
    git pull origin main
    ```

2.  **Install Dependencies**:
    The new version requires `psutil` for health monitoring.
    ```bash
    pip install -r requirements.txt
    ```

3.  **Update Configuration**:
    Update your `.env` file with the new rate limiting variables.
    See `.env.example` for the full list.

    **Key additions:**
    ```ini
    # Gemini API Rate Limiting (Free Tier: 15 RPM, we target 4)
    GEMINI_RPM_INITIAL=4.0
    GEMINI_RPM_MIN=1.0
    GEMINI_RPM_MAX=4.0

    # Process Config
    MARKET_FETCH_INTERVAL_MINUTES=5
    QUEUE_SIZE_LIMIT=100
    HEALTH_CHECK_INTERVAL_SECONDS=60
    ```

    **Deprecated/Removed:**
    *   `API_RATE_LIMIT` (replaced by `GEMINI_RPM_INITIAL`)
    *   `TOP_MARKETS_TO_ANALYZE` (logic replaced by queue priority)

4.  **Directory Setup**:
    Ensure the `data/` directory exists for the new queue database.
    ```bash
    mkdir -p data
    ```

## Running the Bot

Start the bot normally:
```bash
python3 src/main.py
```

## Verification

1.  **Check Logs**:
    You should see "Start Single Run..." replaced by:
    ```
    ✅ Started thread: MarketDiscovery
    ✅ Started thread: QueueProcessor
    ✅ Started thread: HealthMonitor
    ✅ Started thread: ResolutionWorker
    ```

2.  **Check Health Dashboard**:
    A new file `HEALTH_STATUS.md` will be generated within minutes.

3.  **Check Queue Database**:
    A file `data/queue.db` should be created.

## Troubleshooting

*   **ImportError: No module named 'psutil'**: Run `pip install -r requirements.txt`.
*   **High Memory Usage**: Check `HEALTH_STATUS.md`. If memory exceeds 400MB, the bot will log warnings.
*   **429 Errors**: The bot handles these automatically now. Check logs for "Rate Limit Hit (429) - Reporting to limiter".
