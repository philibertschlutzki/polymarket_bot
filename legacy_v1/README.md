# Polymarket AI Value Bot 🤖📈

![Status](https://img.shields.io/badge/Status-Active-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Database](https://img.shields.io/badge/Database-SQLite%20%7C%20Postgres-lightgrey)

An autonomous trading bot that identifies value bets on [Polymarket](https://polymarket.com) using AI-driven probability estimation and the Kelly Criterion.

## 🚀 Features

- **AI Analysis**: Uses **Google Gemini 2.0 Flash** with Search Grounding to estimate real-time probabilities.
- **Value Discovery**: Fetches markets via **Polymarket Gamma API** and filters for high-volume opportunities.
- **Smart Staking**: Calculates optimal bet size using the **Kelly Criterion** to maximize growth while managing risk.
- **Auto-Resolution**: Automatically tracks and resolves bets using **Goldsky Subgraph GraphQL**.
- **Dashboard**: Generates a real-time `PERFORMANCE_DASHBOARD.md` with charts and metrics.
- **Transparency**: Logs detailed AI reasoning in `AI_DECISIONS.md`.
- **Git Sync**: Automatically pushes updates to this repository for remote monitoring.

## 📂 Structure

```
polymarket_bot/
├── src/                # Core source code
│   ├── main.py         # Entry point & scheduler
│   ├── database.py     # Database operations
│   └── ...
├── scripts/            # Deployment & maintenance scripts
├── database/           # SQLite database location
├── docs/               # Detailed documentation
├── tests/              # Unit tests
└── archive/            # Legacy files
```

## 🛠️ Installation

### 1. Prerequisites
- Python 3.10+
- Git
- A Google Gemini API Key (Free tier available)

### 2. Setup
```bash
git clone https://github.com/philibertschlutzki/polymarket_bot.git
cd polymarket_bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy the example environment file and edit it:
```bash
cp .env.example .env
nano .env
```
Fill in:
- `GEMINI_API_KEY`: Your Google AI Studio key.
- `GITHUB_PAT`: (Optional) GitHub Token for auto-push.

### 4. Database Initialization
```bash
python3 -c "from src import database; database.init_database()"
```

### 5. Run
```bash
export PYTHONPATH=$(pwd)
python3 src/main.py
```

## 🤖 API Monitoring

The bot includes a robust API usage tracking system for Gemini:
- **Rate Limiting**: Automatically adheres to Free Tier limits (15 RPM, 1,500 RPD, 1M TPM).
- **Logging**: Tracks every API call in `logs/gemini_api_usage.log`.
- **Reporting**: Generates real-time usage stats in the dashboard and via `src/api_usage_report.py`.

## 📦 Deployment (Raspberry Pi)

Use the automated deployment script:
```bash
bash scripts/deploy_raspberry_pi.sh
```
This script handles dependencies, database setup, log rotation, and installs a `systemd` service.

## 📊 Documentation

- [Architecture](ARCHITECTURE.md)
- [Operations Guide](OPERATIONS.md)
- [Contributing](CONTRIBUTING.md)
- [Database Schema](docs/database_schema.md)
- [API Endpoints](docs/api_endpoints.md)
- [Changelog](CHANGELOG.md)

## ⚖️ Disclaimer

This bot is for educational and experimental purposes only. Prediction markets involve financial risk. The authors are not responsible for any financial losses incurred by using this software. Use at your own risk.

## 📄 License

MIT License
