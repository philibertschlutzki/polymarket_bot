# Database Schema

## Overview
The system uses SQLAlchemy ORM and supports both SQLite (default) and PostgreSQL.
The schema is defined in `src/db_models.py`.

## Tables

### 1. `portfolio_state`
Tracks current capital and global state.
| Column | Type | Description |
|--------|-----|--------------|
| `id` | INTEGER (PK) | Singleton ID (always 1) |
| `total_capital` | NUMERIC | Available capital in USDC |
| `last_updated` | DATETIME | Timestamp of last capital change |
| `last_run_timestamp` | DATETIME | Timestamp of last bot execution |
| `last_dashboard_update`| DATETIME | Timestamp of last dashboard gen |

### 2. `active_bets`
Stores currently open positions.
| Column | Type | Description |
|--------|-----|--------------|
| `bet_id` | BIGINT (PK) | Auto-increment ID |
| `market_slug` | TEXT | Unique Market ID (conditionId) |
| `url_slug` | TEXT | URL-friendly slug |
| `question` | TEXT | Market question |
| `action` | TEXT | 'YES' or 'NO' |
| `stake_usdc` | NUMERIC | Stake amount |
| `entry_price` | NUMERIC | Price at entry (0.0-1.0) |
| `ai_probability` | NUMERIC | Gemini predicted probability |
| `confidence_score` | NUMERIC | AI confidence (0.0-1.0) |
| `expected_value` | NUMERIC | Calculated EV |
| `edge` | NUMERIC | `ai_prob - market_price` |
| `ai_reasoning` | TEXT | Full text reasoning |
| `end_date` | DATETIME | Market expiration |
| `status` | TEXT | 'OPEN' |

### 3. `archived_bets` (Results)
Stores closed or resolved bets.
| Column | Type | Description |
|--------|-----|--------------|
| `archive_id` | BIGINT (PK) | Auto-increment ID |
| `original_bet_id` | BIGINT | Ref to `active_bets` ID |
| ... | ... | (Inherits fields from active_bets) |
| `actual_outcome` | TEXT | 'YES', 'NO', or 'UNRESOLVED' |
| `profit_loss` | NUMERIC | Realized P/L in USDC |
| `roi` | NUMERIC | Return on Investment |
| `timestamp_resolved` | DATETIME | Time of resolution |

### 4. `rejected_markets`
Logs markets analyzed but rejected.
| Column | Type | Description |
|--------|-----|--------------|
| `rejection_id` | BIGINT (PK) | Auto-increment ID |
| `rejection_reason` | TEXT | e.g., 'INSUFFICIENT_EDGE', 'NEGATIVE_EV' |
| ... | ... | Market details and AI stats |

### 5. `api_usage`
Logs API consumption for monitoring.
| Column | Type | Description |
|--------|-----|--------------|
| `log_id` | BIGINT (PK) | Auto-increment ID |
| `api_name` | TEXT | 'gemini', 'polymarket', etc. |
| `tokens_prompt` | INTEGER | Input tokens |
| `tokens_response` | INTEGER | Output tokens |
| `response_time_ms` | INTEGER | Latency |

### 6. `git_sync_state`
Manages state for auto-push logic.
| Column | Type | Description |
|--------|-----|--------------|
| `id` | INTEGER (PK) | Singleton ID (1) |
| `pending_changes_count`| INTEGER | Number of changes since last push |
| `has_new_bets` | BOOLEAN | Flag |

## Relationships
- `active_bets` moves to `archived_bets` upon resolution.
- `bet_analysis` (optional/experimental) links to `archived_bets`.
