import sqlite3
import os
import logging
import math
from datetime import datetime
from contextlib import contextmanager
from typing import List, Optional, Dict, Any, Tuple
from dateutil import parser

# Configuration
DB_NAME = 'polymarket.db'
INITIAL_CAPITAL = 1000.0

# Logging
logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """Context manager for SQLite database connection."""
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row  # Access columns by name
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    """Initializes the database with required tables and default values."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Portfolio State (Single Row)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_capital REAL NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            last_dashboard_update TIMESTAMP
        )
        ''')

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

        # Initialize capital if empty
        cursor.execute('SELECT count(*) FROM portfolio_state')
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                'INSERT INTO portfolio_state (id, total_capital, last_updated) VALUES (?, ?, ?)',
                (1, INITIAL_CAPITAL, datetime.now())
            )
            logger.info(f"Initialized portfolio with ${INITIAL_CAPITAL} USDC")

        conn.commit()
        logger.info("Database initialized successfully.")

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
            (new_capital, datetime.now())
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
            bet_data.get('end_date'),
            datetime.now()
        ))
        conn.commit()
        logger.info(f"New bet recorded: {bet_data['question'][:30]}... (${bet_data['stake_usdc']})")

def get_active_bets() -> List[sqlite3.Row]:
    """Retrieves all OPEN bets."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_bets WHERE status = 'OPEN'")
        return cursor.fetchall()

def close_bet(bet_id: int, outcome: str, profit_loss: float):
    """Moves a bet from active_bets to results and updates capital."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get bet details
        cursor.execute("SELECT * FROM active_bets WHERE bet_id = ?", (bet_id,))
        bet = cursor.fetchone()
        if not bet:
            logger.error(f"Bet {bet_id} not found!")
            return

        # Calculate ROI
        roi = (profit_loss / bet['stake_usdc']) if bet['stake_usdc'] > 0 else 0.0

        # Insert into results
        cursor.execute('''
        INSERT INTO results (
            bet_id, market_slug, question, action, stake_usdc, entry_price,
            actual_outcome, profit_loss, roi, timestamp_created, timestamp_closed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            bet['bet_id'], bet['market_slug'], bet['question'], bet['action'],
            bet['stake_usdc'], bet['entry_price'], outcome, profit_loss, roi,
            bet['timestamp_created'], datetime.now()
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
            (new_capital, datetime.now())
        )

        conn.commit()
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
            (datetime.now(),)
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
