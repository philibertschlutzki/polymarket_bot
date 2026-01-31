import sqlite3
import os
import logging
import math
import threading
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager, nullcontext
from typing import List, Optional, Dict, Any, Tuple
from dateutil import parser

# Configuration
DB_NAME = 'polymarket.db'
INITIAL_CAPITAL = 1000.0

# Logging
logger = logging.getLogger(__name__)

# Thread-local storage for database connections
_local = threading.local()

def flexible_timestamp_converter(val):
    """
    Custom SQLite converter to handle various timestamp formats.
    Handles 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', etc.
    """
    if not val:
        return None
    try:
        # Handle bytes (SQLite default) or string (if manual)
        s = val.decode('utf-8') if isinstance(val, bytes) else str(val)

        # Explicitly handle date-only strings to ensure time is attached
        if len(s) == 10 and s.count('-') == 2:
             s = f"{s} 00:00:00"

        return parser.parse(s)
    except Exception as e:
        logger.warning(f"Error parsing timestamp '{val}': {e}")
        return None

def register_adapters():
    """Registers SQLite adapters and converters."""
    sqlite3.register_converter("TIMESTAMP", flexible_timestamp_converter)

# Register the converter
register_adapters()

def safe_timestamp(val):
    """
    Ensures timestamp is converted to a standard string format before insertion.
    Returns 'YYYY-MM-DD HH:MM:SS' string.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(val, str):
        try:
            dt = parser.parse(val)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            # Fallback for date only strings if parse fails (unlikely if valid)
            if len(val) == 10 and val.count('-') == 2:
                return f"{val} 00:00:00"
            return val
    return val

@contextmanager
def get_db_connection():
    """
    Context manager for SQLite database connection.
    Uses thread-local storage to reuse connections.
    Handles nested usage by tracking recursion depth.
    """
    if not hasattr(_local, "connection") or _local.connection is None:
        # Ensure adapters are registered for this thread/connection
        register_adapters()

        conn = sqlite3.connect(
            DB_NAME,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
            timeout=30.0
        )
        conn.row_factory = sqlite3.Row  # Access columns by name
        _local.connection = conn
        _local.depth = 0

    conn = _local.connection
    # Ensure depth is initialized (in case _local.connection existed but depth didn't for some reason)
    if not hasattr(_local, "depth"):
        _local.depth = 0

    _local.depth += 1

    try:
        yield conn
    finally:
        _local.depth -= 1
        if _local.depth == 0:
            # Instead of closing, we rollback any uncommitted changes to ensure clean state
            # for the next usage. This mimics conn.close() behavior regarding transactions
            # but keeps the connection open.
            conn.rollback()

def close_db_connection():
    """Manually closes the thread-local database connection if it exists."""
    if hasattr(_local, "connection") and _local.connection is not None:
        try:
            _local.connection.close()
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")
        finally:
            _local.connection = None
            _local.depth = 0

def repair_timestamps():
    """
    Scans active_bets and results tables for invalid timestamps and fixes them.
    """
    logger.info("Checking for malformed timestamps in database...")
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Check active_bets
        try:
            cursor.execute("SELECT bet_id, timestamp_created, end_date FROM active_bets")
            rows = cursor.fetchall()
            for row in rows:
                updates = {}
                # Check timestamp_created
                ts_created = row['timestamp_created']

                if ts_created:
                    updates['timestamp_created'] = safe_timestamp(ts_created)

                end_date = row['end_date']
                if end_date:
                    updates['end_date'] = safe_timestamp(end_date)

                if updates:
                    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                    values = list(updates.values()) + [row['bet_id']]
                    cursor.execute(f"UPDATE active_bets SET {set_clause} WHERE bet_id = ?", values)

            # Check results
            cursor.execute("SELECT result_id, timestamp_created, timestamp_closed FROM results")
            rows = cursor.fetchall()
            for row in rows:
                updates = {}
                ts_created = row['timestamp_created']
                if ts_created:
                    updates['timestamp_created'] = safe_timestamp(ts_created)

                ts_closed = row['timestamp_closed']
                if ts_closed:
                    updates['timestamp_closed'] = safe_timestamp(ts_closed)

                if updates:
                    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                    values = list(updates.values()) + [row['result_id']]
                    cursor.execute(f"UPDATE results SET {set_clause} WHERE result_id = ?", values)

            conn.commit()
            logger.info("Timestamp repair completed.")

        except Exception as e:
            logger.error(f"Error during timestamp repair: {e}")

def init_database():
    """Initializes the database with required tables and default values."""
    register_adapters() # Ensure registered

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Portfolio State (Single Row)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_capital REAL NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            last_dashboard_update TIMESTAMP,
            last_run_timestamp TIMESTAMP
        )
        ''')

        # Check if last_run_timestamp exists (migration)
        try:
            cursor.execute("SELECT last_run_timestamp FROM portfolio_state LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating database: Adding last_run_timestamp to portfolio_state")
            cursor.execute("ALTER TABLE portfolio_state ADD COLUMN last_run_timestamp TIMESTAMP")

        # Active Bets
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_bets (
            bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('YES', 'NO')),
            stake_usdc REAL NOT NULL,
            entry_price REAL NOT NULL,
            ai_probability REAL NOT NULL,
            confidence_score REAL NOT NULL,
            expected_value REAL NOT NULL,
            end_date TIMESTAMP,
            timestamp_created TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED'))
        )
        ''')

        # Check if end_date exists (migration)
        try:
            cursor.execute("SELECT end_date FROM active_bets LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating database: Adding end_date to active_bets")
            cursor.execute("ALTER TABLE active_bets ADD COLUMN end_date TIMESTAMP")

        # Results (Closed Bets)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id INTEGER NOT NULL,
            market_slug TEXT NOT NULL,
            question TEXT NOT NULL,
            action TEXT NOT NULL,
            stake_usdc REAL NOT NULL,
            entry_price REAL NOT NULL,
            actual_outcome TEXT CHECK (actual_outcome IN ('YES', 'NO')),
            profit_loss REAL NOT NULL,
            roi REAL NOT NULL,
            timestamp_created TIMESTAMP NOT NULL,
            timestamp_closed TIMESTAMP NOT NULL,
            FOREIGN KEY (bet_id) REFERENCES active_bets(bet_id)
        )
        ''')

        # API Usage Tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            api_name TEXT NOT NULL,
            endpoint TEXT,
            calls INTEGER DEFAULT 1,
            tokens_prompt INTEGER DEFAULT 0,
            tokens_response INTEGER DEFAULT 0,
            tokens_total INTEGER DEFAULT 0,
            response_time_ms INTEGER DEFAULT 0
        )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_timestamp ON api_usage(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_name ON api_usage(api_name, timestamp)')

        # Initialize capital if empty
        cursor.execute('SELECT count(*) FROM portfolio_state')
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                'INSERT INTO portfolio_state (id, total_capital, last_updated) VALUES (?, ?, ?)',
                (1, INITIAL_CAPITAL, safe_timestamp(datetime.now()))
            )
            logger.info(f"Initialized portfolio with ${INITIAL_CAPITAL} USDC")

        conn.commit()
        logger.info("Database initialized successfully.")

    # Run repair after initialization to fix any existing issues
    repair_timestamps()

def get_current_capital() -> float:
    """Reads current capital from portfolio_state."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT total_capital FROM portfolio_state WHERE id = 1')
        row = cursor.fetchone()
        if row:
            return row['total_capital']
        return INITIAL_CAPITAL

def update_capital(new_capital: float):
    """Updates total capital in portfolio_state."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE portfolio_state SET total_capital = ?, last_updated = ? WHERE id = 1',
            (new_capital, safe_timestamp(datetime.now()))
        )
        conn.commit()
        logger.info(f"Capital updated to ${new_capital:.2f}")

def insert_active_bet(bet_data: Dict[str, Any]):
    """Inserts a new active bet."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute('''
        INSERT INTO active_bets (
            market_slug, question, action, stake_usdc, entry_price,
            ai_probability, confidence_score, expected_value, end_date,
            timestamp_created, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        ''', (
            bet_data['market_slug'],
            bet_data['question'],
            bet_data['action'],
            bet_data['stake_usdc'],
            bet_data['entry_price'],
            bet_data['ai_probability'],
            bet_data['confidence_score'],
            bet_data['expected_value'],
            safe_timestamp(bet_data.get('end_date')),
            safe_timestamp(datetime.now())
        ))
        conn.commit()
        logger.info(f"New bet recorded: {bet_data['question'][:30]}... (${bet_data['stake_usdc']})")

def get_active_bets() -> List[sqlite3.Row]:
    """Retrieves all OPEN bets."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_bets WHERE status = 'OPEN'")
        return cursor.fetchall()

def close_bet(bet_id: int, outcome: str, profit_loss: float, conn: Optional[sqlite3.Connection] = None):
    """Moves a bet from active_bets to results and updates capital."""

    should_commit = conn is None
    ctx = get_db_connection() if conn is None else nullcontext(conn)

    with ctx as db_conn:
        cursor = db_conn.cursor()

        # Get bet details
        cursor.execute("SELECT * FROM active_bets WHERE bet_id = ?", (bet_id,))
        bet = cursor.fetchone()
        if not bet:
            logger.error(f"Bet {bet_id} not found!")
            return

        # Calculate ROI
        roi = (profit_loss / bet['stake_usdc']) if bet['stake_usdc'] > 0 else 0.0

        # Insert into results
        # Note: We use the original timestamp_created from the bet, but ensure it's safe
        cursor.execute('''
        INSERT INTO results (
            bet_id, market_slug, question, action, stake_usdc, entry_price,
            actual_outcome, profit_loss, roi, timestamp_created, timestamp_closed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            bet['bet_id'], bet['market_slug'], bet['question'], bet['action'],
            bet['stake_usdc'], bet['entry_price'], outcome, profit_loss, roi,
            safe_timestamp(bet['timestamp_created']), safe_timestamp(datetime.now())
        ))

        # Update active_bet status
        cursor.execute("UPDATE active_bets SET status = 'CLOSED' WHERE bet_id = ?", (bet_id,))

        # Update Capital
        cursor.execute('SELECT total_capital FROM portfolio_state WHERE id = 1')
        current_capital_row = cursor.fetchone()
        current_capital = current_capital_row['total_capital'] if current_capital_row else INITIAL_CAPITAL
        new_capital = current_capital + profit_loss

        cursor.execute(
            'UPDATE portfolio_state SET total_capital = ?, last_updated = ? WHERE id = 1',
            (new_capital, safe_timestamp(datetime.now()))
        )

        if should_commit:
            db_conn.commit()
        logger.info(f"Bet {bet_id} closed. Outcome: {outcome}. P/L: ${profit_loss:.2f}. New Capital: ${new_capital:.2f}")

def get_all_results() -> List[sqlite3.Row]:
    """Retrieves all closed bets (results)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM results ORDER BY timestamp_closed DESC")
        return cursor.fetchall()

def calculate_metrics() -> Dict[str, Any]:
    """Calculates performance metrics (Win Rate, ROI, Sharpe, Drawdown)."""
    results = get_all_results()

    if not results:
        return {
            "total_bets": 0,
            "win_rate": 0.0,
            "avg_roi": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_return_usd": 0.0,
            "total_return_percent": 0.0,
            "best_bet_usd": 0.0,
            "worst_bet_usd": 0.0
        }

    wins = 0
    total_roi = 0.0
    returns = []
    capital_curve = [INITIAL_CAPITAL]
    current_cap = INITIAL_CAPITAL

    best_bet = -float('inf')
    worst_bet = float('inf')
    total_pl = 0.0

    # Sort results by closed time to build curve
    # results is a list of sqlite3.Row, need to convert to list to sort if not already sorted by SQL
    sorted_results = sorted(results, key=lambda x: x['timestamp_closed'])

    for res in sorted_results:
        pl = res['profit_loss']
        total_pl += pl
        if pl > 0:
            wins += 1

        total_roi += res['roi']
        returns.append(res['roi'])

        current_cap += pl
        capital_curve.append(current_cap)

        if pl > best_bet:
            best_bet = pl
        if pl < worst_bet:
            worst_bet = pl

    total_bets = len(results)
    win_rate = wins / total_bets
    avg_roi = total_roi / total_bets

    # Sharpe Ratio
    if total_bets > 1:
        mean_return = sum(returns) / total_bets
        variance = sum((x - mean_return) ** 2 for x in returns) / (total_bets - 1)
        std_dev = math.sqrt(variance)
        sharpe = (mean_return / std_dev) if std_dev > 0 else 0.0
    else:
        sharpe = 0.0

    # Max Drawdown
    peak = capital_curve[0]
    max_dd = 0.0

    for val in capital_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd

    total_return_usd = current_cap - INITIAL_CAPITAL
    total_return_percent = (total_return_usd / INITIAL_CAPITAL)

    return {
        "total_bets": total_bets,
        "win_rate": win_rate,
        "avg_roi": avg_roi,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "total_return_usd": total_return_usd,
        "total_return_percent": total_return_percent,
        "best_bet_usd": best_bet if total_bets > 0 else 0.0,
        "worst_bet_usd": worst_bet if total_bets > 0 else 0.0
    }

def update_last_dashboard_update():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE portfolio_state SET last_dashboard_update = ? WHERE id = 1',
            (safe_timestamp(datetime.now()),)
        )
        conn.commit()

def get_last_dashboard_update() -> Optional[datetime]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT last_dashboard_update FROM portfolio_state WHERE id = 1')
        row = cursor.fetchone()
        if row and row['last_dashboard_update']:
            val = row['last_dashboard_update']
            # If adapter works, val is datetime. If not, it is bytes or str.
            if isinstance(val, (bytes, str)):
                 return parser.parse(val)
            return val
        return None

# ============================================================================
# NEW API TRACKING FUNCTIONS
# ============================================================================

def log_api_usage(api_name: str, endpoint: str, tokens_prompt: int, tokens_response: int, response_time_ms: int):
    """Log API usage to the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO api_usage (
            timestamp, api_name, endpoint, tokens_prompt, tokens_response, tokens_total, response_time_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            safe_timestamp(datetime.now(timezone.utc)), # Store as UTC
            api_name,
            endpoint,
            tokens_prompt,
            tokens_response,
            tokens_prompt + tokens_response,
            response_time_ms
        ))
        conn.commit()

def get_api_usage_rpm(api_name: str = "gemini") -> int:
    """Returns number of API calls in the last minute."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        one_min_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        cursor.execute(
            "SELECT COUNT(*) FROM api_usage WHERE api_name = ? AND timestamp >= ?",
            (api_name, safe_timestamp(one_min_ago))
        )
        return cursor.fetchone()[0]

def get_api_usage_rpd(api_name: str = "gemini") -> int:
    """Returns number of API calls today (UTC based, effectively)."""
    # Note: Requirement says "CET", but prompt implementation in step 5 assumes UTC storage and display conversion.
    # To strictly follow "today (CET)", we need to calculate start of day in CET.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now_utc = datetime.now(timezone.utc)
        # Approximate CET (UTC+1) for simple day boundary if timezone lib not fully utilized for queries
        # Or better, just count last 24h or day since midnight UTC.
        # Requirement: "today (CET)".
        # Let's try to get start of day CET in UTC.
        cet_offset = timedelta(hours=1) # Simplified, ignoring DST
        now_cet = now_utc + cet_offset
        start_of_day_cet = now_cet.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day_cet - cet_offset

        cursor.execute(
            "SELECT COUNT(*) FROM api_usage WHERE api_name = ? AND timestamp >= ?",
            (api_name, safe_timestamp(start_of_day_utc))
        )
        return cursor.fetchone()[0]

def get_api_usage_tpm(api_name: str = "gemini") -> int:
    """Returns sum of tokens in the last minute."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        one_min_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        cursor.execute(
            "SELECT SUM(tokens_total) FROM api_usage WHERE api_name = ? AND timestamp >= ?",
            (api_name, safe_timestamp(one_min_ago))
        )
        result = cursor.fetchone()[0]
        return result if result else 0

def get_last_run_timestamp() -> Optional[datetime]:
    """Reads last run timestamp from DB."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT last_run_timestamp FROM portfolio_state WHERE id = 1')
        row = cursor.fetchone()
        if row and row['last_run_timestamp']:
            val = row['last_run_timestamp']
            if isinstance(val, (bytes, str)):
                 return parser.parse(val)
            return val
        return None

def set_last_run_timestamp(timestamp: datetime):
    """Saves last run timestamp."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE portfolio_state SET last_run_timestamp = ? WHERE id = 1',
            (safe_timestamp(timestamp),)
        )
        conn.commit()
