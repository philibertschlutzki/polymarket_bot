# System Architecture

## Overview
The Polymarket Bot is an autonomous trading system that analyzes prediction markets, estimates probabilities using AI (Google Gemini 2.0 Flash), and executes trades based on the Kelly Criterion. It runs on a Raspberry Pi or Linux server.

## System Diagram

```mermaid
graph TD
    A[Polymarket Gamma API] -->|Market Data| B[src/main.py]
    B -->|Filter Markets| C{Pre-Filter}
    C -->|High Value| D[Gemini AI]
    D -->|Probability & Reasoning| E[Kelly Criterion]
    E -->|Stake Size| F[Database (SQLite/Postgres)]
    F -->|Store Bet| G[src/database.py]

    H[Goldsky GraphQL] -->|Resolution Status| B

    B -->|Update Stats| I[src/dashboard.py]
    I -->|Generate MD| J[PERFORMANCE_DASHBOARD.md]

    B -->|Log Decisions| K[src/ai_decisions_generator.py]
    K -->|Generate MD| L[AI_DECISIONS.md]

    J & L -->|Auto Push| M[src/git_integration.py]
    M -->|Git Push| N[GitHub Repository]
```

## Core Modules (`src/`)

### `main.py`
The entry point and scheduler.
- Runs every 15 minutes.
- Fetches markets from Polymarket API.
- Filters markets based on volume and price.
- Calls Gemini AI for analysis.
- Calculates stake using Kelly Criterion.
- Orchestrates database updates, dashboard generation, and git sync.

### `database.py` & `db_models.py`
Data persistence layer.
- Uses SQLAlchemy for ORM.
- Supports SQLite (default) and PostgreSQL.
- Manages `active_bets`, `archived_bets`, `rejected_markets`, `portfolio_state`, etc.
- Handles atomic updates for capital and results.

### `dashboard.py`
Reporting engine.
- Generates `PERFORMANCE_DASHBOARD.md` from database stats.
- Visualizes metrics (ROI, Win Rate, Drawdown) and active bets.

### `ai_decisions_generator.py`
Audit log generator.
- Creates `AI_DECISIONS.md` detailing every trade and rejection.
- Includes full AI reasoning text.

### `analytics_advanced.py`
Statistical analysis.
- Calculates Confidence Calibration, Edge Validation, and Model Trends.

### `git_integration.py`
Automation.
- Pushes updated dashboards and decision logs to GitHub automatically.

## External APIs

1.  **Polymarket Gamma API (REST)**
    - Used for market discovery (`/markets`).
    - Source of volume, question, description.

2.  **Goldsky Subgraph (GraphQL)**
    - Used for precise market resolution and outcome prices.
    - Handles batch queries for efficiency.

3.  **Google Gemini API**
    - Model: `gemini-2.0-flash`
    - Feature: Search Grounding (web access) for up-to-date probability estimation.

## Data Flow
1.  **Fetch**: Get open markets from Gamma API.
2.  **Filter**: Exclude low volume (<$10k) or extreme odds (<5% or >95%).
3.  **Analyze**: Send top 15 candidates to Gemini AI.
4.  **Decide**: AI returns probability. Calculate Edge = AI_Prob - Market_Price.
5.  **Bet**: If Edge > 0 and EV > 0, calculate Kelly stake.
6.  **Store**: Save to `active_bets`.
7.  **Resolve**: Check expired bets against Goldsky. Move to `archived_bets` with P/L.
8.  **Report**: Update dashboards and push to Git.
