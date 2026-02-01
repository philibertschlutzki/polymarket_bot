# Operations Guide

## Deployment

### Raspberry Pi (Recommended)
1.  Clone the repository:
    ```bash
    git clone https://github.com/philibertschlutzki/polymarket_bot.git
    cd polymarket_bot
    ```
2.  Run the deployment script:
    ```bash
    bash scripts/deploy_raspberry_pi.sh
    ```
    - This will install Python, Git, create a venv, install dependencies, and setup a systemd service.
    - It handles database initialization (SQLite by default).

### Manual Linux Setup
1.  Install Python 3.10+ and Git.
2.  Clone and setup venv:
    ```bash
    git clone <repo>
    cd polymarket_bot
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
3.  Configure `.env`:
    ```bash
    cp .env.example .env
    nano .env
    ```
4.  Run:
    ```bash
    export PYTHONPATH=$(pwd)
    python3 src/main.py
    ```

## Monitoring

### Service Status
Check if the bot is running:
```bash
sudo systemctl status polymarket-bot
```

### Live Logs
Watch the logs in real-time:
```bash
tail -f logs/bot.log
```
Or specifically for errors:
```bash
tail -f logs/errors.log
```

### Dashboard
The bot automatically updates `PERFORMANCE_DASHBOARD.md` in the repo. Check the GitHub interface or the file locally to see stats.

## Maintenance

### Database Backup (SQLite)
The database is located at `database/polymarket.db`.
To backup:
```bash
cp database/polymarket.db database/polymarket_backup_$(date +%Y%m%d).db
```

### Updates
To update the bot code:
```bash
cd /home/pi/polymarket_bot
git pull origin main
sudo systemctl restart polymarket-bot
```

### Log Rotation
Logs are rotated daily and kept for 7 days.
Configuration is at `/etc/logrotate.d/polymarket-bot`.

## Troubleshooting

### "Connection refused" (PostgreSQL)
- Ensure you are using SQLite (default) by commenting out `DATABASE_URL` in `.env`.
- If using Postgres, check if the service is running (`sudo systemctl status postgresql`).

### "Permission denied"
- Run the fix script:
  ```bash
  bash scripts/fix_permissions.sh
  ```

### API Rate Limits
- If you see API rate limit warnings in logs, increase the cycle time or reduce `TOP_MARKETS_TO_ANALYZE` in `.env`.
