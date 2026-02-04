import os
import sqlite3
import sys

from sqlalchemy import create_engine, text

# Set env var before importing src modules
test_db_path = "test_migration.db"
if os.path.exists(test_db_path):
    os.remove(test_db_path)
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"

# Add src to path
sys.path.append(os.getcwd())

from src.database import engine, migrate_archived_bets_table


def setup_broken_table():
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS archived_bets"))
        # Create table WITHOUT AUTOINCREMENT (explicitly missing it)
        # Standard CREATE TABLE with INTEGER PRIMARY KEY is autoincrement in SQLite usually,
        # but NOT GUARANTEED to be sequential or support RETURNING if not strict?
        # Actually, "AUTOINCREMENT" keyword is specific.
        # Without it, it's just a rowid alias.
        conn.execute(text("""
            CREATE TABLE archived_bets (
                archive_id INTEGER PRIMARY KEY,
                original_bet_id BIGINT NOT NULL UNIQUE,
                market_slug TEXT NOT NULL,
                url_slug TEXT NOT NULL,
                question TEXT NOT NULL,
                action TEXT NOT NULL,
                stake_usdc NUMERIC(10, 2) NOT NULL,
                entry_price NUMERIC(5, 4) NOT NULL,
                ai_probability NUMERIC(5, 4) NOT NULL,
                confidence_score NUMERIC(5, 4) NOT NULL,
                edge NUMERIC(6, 4),
                ai_reasoning TEXT,
                timestamp_created DATETIME NOT NULL,
                timestamp_archived DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                end_date DATETIME,
                actual_outcome TEXT,
                profit_loss NUMERIC(10, 2),
                roi NUMERIC(6, 4),
                timestamp_resolved DATETIME,
                version INTEGER NOT NULL DEFAULT 1
            )
        """))

        # Insert dummy data
        conn.execute(text("""
            INSERT INTO archived_bets (
                archive_id, original_bet_id, market_slug, url_slug, question, action,
                stake_usdc, entry_price, ai_probability, confidence_score,
                timestamp_created
            ) VALUES (
                100, 12345, 'slug', 'url', 'q', 'YES',
                10, 0.5, 0.6, 0.8,
                '2024-01-01 00:00:00'
            )
        """))
        conn.commit()


def verify_autoincrement_missing():
    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='archived_bets'")
        ).scalar()
        if "AUTOINCREMENT" in sql:
            raise Exception("Table unexpectedly has AUTOINCREMENT already!")
        print("Verified: Table is missing AUTOINCREMENT.")


def verify_migration_success():
    with engine.connect() as conn:
        # Check schema
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='archived_bets'")
        ).scalar()
        if "AUTOINCREMENT" not in sql:
            raise Exception("Migration failed: AUTOINCREMENT not found in schema!")
        print("Verified: Table now has AUTOINCREMENT.")

        # Check data preservation
        row = conn.execute(
            text("SELECT * FROM archived_bets WHERE archive_id=100")
        ).fetchone()
        if not row:
            raise Exception("Migration failed: Data lost!")
        if row.original_bet_id != 12345:
            raise Exception("Migration failed: Data corrupted!")
        print("Verified: Data preserved.")


def main():
    try:
        print("Setting up broken table...")
        setup_broken_table()

        verify_autoincrement_missing()

        print("Running migration...")
        migrate_archived_bets_table()

        verify_migration_success()

        print("SUCCESS: Migration worked as expected.")
    except Exception as e:
        print(f"FAILURE: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


if __name__ == "__main__":
    main()
