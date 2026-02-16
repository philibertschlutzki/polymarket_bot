import sqlite3
import os

DB_PATH = "database/polymarket.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. Migrate active_bets
        print("Migrating active_bets...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='active_bets'")
        if cursor.fetchone():
            # Check if columns already exist to avoid unnecessary work or double migration
            # Actually, simply recreating ensures we have the correct schema (removing UNIQUE)

            # Rename old
            cursor.execute("DROP TABLE IF EXISTS active_bets_backup")
            cursor.execute("ALTER TABLE active_bets RENAME TO active_bets_backup")

            # Create new (Copied from DDL matching new db_models.py)
            # Note: unique constraint on market_slug is GONE.
            cursor.execute("""
                CREATE TABLE active_bets (
                    bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_slug TEXT NOT NULL,
                    parent_event_slug TEXT,
                    outcome_variant_id TEXT,
                    is_multi_outcome BOOLEAN DEFAULT 0 NOT NULL,
                    url_slug TEXT NOT NULL,
                    question TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('YES', 'NO')),
                    stake_usdc NUMERIC(10, 2) NOT NULL CHECK(stake_usdc > 0),
                    entry_price NUMERIC(5, 4) NOT NULL CHECK(entry_price BETWEEN 0 AND 1),
                    ai_probability NUMERIC(5, 4) NOT NULL CHECK(ai_probability BETWEEN 0 AND 1),
                    confidence_score NUMERIC(5, 4) NOT NULL CHECK(confidence_score BETWEEN 0 AND 1),
                    expected_value NUMERIC(10, 2) NOT NULL,
                    edge NUMERIC(6, 4),
                    ai_reasoning TEXT,
                    end_date DATETIME,
                    timestamp_created DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'PENDING_RESOLUTION')),
                    version INTEGER NOT NULL DEFAULT 1
                )
            """)

            # Create index for parent_event_slug
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_active_bets_parent_event_slug ON active_bets (parent_event_slug)")

            # Copy data
            # New columns default to NULL or False
            cursor.execute("""
                INSERT INTO active_bets (
                    bet_id, market_slug, url_slug, question, action, stake_usdc,
                    entry_price, ai_probability, confidence_score, expected_value,
                    edge, ai_reasoning, end_date, timestamp_created, status, version
                )
                SELECT
                    bet_id, market_slug, url_slug, question, action, stake_usdc,
                    entry_price, ai_probability, confidence_score, expected_value,
                    edge, ai_reasoning, end_date, timestamp_created, status, version
                FROM active_bets_backup
            """)

            cursor.execute("DROP TABLE active_bets_backup")
            print("active_bets migrated.")

        # 2. Migrate archived_bets
        print("Migrating archived_bets...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='archived_bets'")
        if cursor.fetchone():
            # Rename old
            cursor.execute("DROP TABLE IF EXISTS archived_bets_backup")
            cursor.execute("ALTER TABLE archived_bets RENAME TO archived_bets_backup")

            # Create new
            cursor.execute("""
                CREATE TABLE archived_bets (
                    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_bet_id INTEGER NOT NULL UNIQUE,
                    market_slug TEXT NOT NULL,
                    parent_event_slug TEXT,
                    outcome_variant_id TEXT,
                    is_multi_outcome BOOLEAN DEFAULT 0 NOT NULL,
                    url_slug TEXT NOT NULL,
                    question TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('YES', 'NO')),
                    stake_usdc NUMERIC(10, 2) NOT NULL CHECK(stake_usdc > 0),
                    entry_price NUMERIC(5, 4) NOT NULL CHECK(entry_price BETWEEN 0 AND 1),
                    ai_probability NUMERIC(5, 4) NOT NULL CHECK(ai_probability BETWEEN 0 AND 1),
                    confidence_score NUMERIC(5, 4) NOT NULL CHECK(confidence_score BETWEEN 0 AND 1),
                    edge NUMERIC(6, 4),
                    ai_reasoning TEXT,
                    timestamp_created DATETIME NOT NULL,
                    timestamp_archived DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    end_date DATETIME,
                    actual_outcome TEXT CHECK(actual_outcome IN ('YES', 'NO', 'UNRESOLVED', 'AUTO_LOSS', 'DISPUTED', 'DISPUTED_LOSS', 'ANNULLED')),
                    profit_loss NUMERIC(10, 2),
                    roi NUMERIC(6, 4),
                    timestamp_resolved DATETIME,
                    version INTEGER NOT NULL DEFAULT 1
                )
            """)

            # Create index for parent_event_slug
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_archived_bets_parent_event_slug ON archived_bets (parent_event_slug)")

            # Copy data
            cursor.execute("""
                INSERT INTO archived_bets (
                    archive_id, original_bet_id, market_slug, url_slug, question, action,
                    stake_usdc, entry_price, ai_probability, confidence_score,
                    edge, ai_reasoning, timestamp_created, timestamp_archived,
                    end_date, actual_outcome, profit_loss, roi, timestamp_resolved, version
                )
                SELECT
                    archive_id, original_bet_id, market_slug, url_slug, question, action,
                    stake_usdc, entry_price, ai_probability, confidence_score,
                    edge, ai_reasoning, timestamp_created, timestamp_archived,
                    end_date, actual_outcome, profit_loss, roi, timestamp_resolved, version
                FROM archived_bets_backup
            """)

            cursor.execute("DROP TABLE archived_bets_backup")
            print("archived_bets migrated.")

        conn.commit()
        print("Migration complete.")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
