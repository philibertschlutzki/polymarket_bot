# Nautilus Trader & Polymarket Integration (V2)

## System Architecture
- **Engine:** Nautilus Trader (Rust/Python)
- **Strategy:** Sentiment Analysis via Google Gemini 2.0 (Search Grounding)
- **Execution:** Polymarket (Polygon PoS)
- **Deployment:** - **Local:** High-performance dev & backtesting.
  - **Cloud:** Lightweight execution node (1GB RAM) via GitHub Actions.

## Structure
- `legacy_v1/`: Archived code.
- `nautilus_v2/`: New trading engine.
  - `strategies/`: Python logic (Gemini integration).
  - `config/`: TOML configuration.
