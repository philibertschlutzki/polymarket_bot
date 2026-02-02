"""
Script to fix database integrity issues for Issues #72 and #74
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from sqlalchemy import text
from src.db_models import engine
from src.database import migrate_api_usage_table, init_database
# ... rest of the code

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_database():
    """Fix database integrity issues."""
    try:
        # 1. Run api_usage migration
        logger.info("Starting api_usage table migration...")
        migrate_api_usage_table()

        # 2. Check and fix rejected_markets table
        logger.info("Checking rejected_markets table...")
        with engine.connect() as conn:
            table_sql = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='rejected_markets'")
            ).fetchone()

            if table_sql and 'AUTOINCREMENT' not in table_sql[0]:
                logger.info("Migrating rejected_markets table...")

                # Backup
                conn.execute(text("DROP TABLE IF EXISTS rejected_markets_backup"))
                conn.execute(text("ALTER TABLE rejected_markets RENAME TO rejected_markets_backup"))
                conn.commit()

                # Recreate
                from src.db_models import RejectedMarket
                RejectedMarket.__table__.create(engine, checkfirst=False)

                # Restore data
                conn.execute(text("""
                    INSERT INTO rejected_markets (
                        market_slug, url_slug, question, market_price, volume,
                        ai_probability, confidence_score, edge, rejection_reason,
                        ai_reasoning, timestamp_analyzed, end_date
                    )
                    SELECT
                        market_slug, url_slug, question, market_price, volume,
                        ai_probability, confidence_score, edge, rejection_reason,
                        ai_reasoning, timestamp_analyzed, end_date
                    FROM rejected_markets_backup
                """))
                conn.execute(text("DROP TABLE rejected_markets_backup"))
                conn.commit()

                logger.info("rejected_markets table migration completed.")
            else:
                logger.info("rejected_markets table already has correct schema.")

        logger.info("Database fix completed successfully!")

    except Exception as e:
        logger.error(f"Error fixing database: {e}")
        raise

if __name__ == "__main__":
    fix_database()
