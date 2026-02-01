import os
import sys
import unittest
from sqlalchemy import text

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set a test database URL before importing modules that create engine
TEST_DB_URL = "sqlite:///test_issue_72.db"
os.environ["DATABASE_URL"] = TEST_DB_URL

# Remove previous DB file if exists
if os.path.exists("test_issue_72.db"):
    os.remove("test_issue_72.db")

from src import database, db_models

class TestIssue72(unittest.TestCase):
    def tearDown(self):
        # Optional: cleanup
        pass

    def test_migration_and_fix(self):
        engine = db_models.engine

        # 1. Manually create the "broken" table (no autoincrement behavior)
        # We explicitly define it without PRIMARY KEY or with strict constraints that fail
        # when we try to insert without ID, mimicking the reported issue.
        print("Creating broken table...")
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS api_usage"))
            # Creating without AUTOINCREMENT (INTEGER PRIMARY KEY in SQLite is autoincrement,
            # so we avoid declaring it as such to reproduce the error)
            conn.execute(text("""
                CREATE TABLE api_usage (
                    id INTEGER NOT NULL,
                    timestamp TIMESTAMP,
                    api_name TEXT,
                    endpoint TEXT,
                    calls INTEGER,
                    tokens_prompt INTEGER,
                    tokens_response INTEGER,
                    tokens_total INTEGER,
                    response_time_ms INTEGER
                )
            """))
            # Insert some initial data (must provide ID manually)
            conn.execute(text("""
                INSERT INTO api_usage (id, api_name, calls, timestamp) VALUES (999, 'existing_data', 5, '2023-01-01 00:00:00')
            """))
            conn.commit()

        # 2. Verify it fails to insert without ID
        print("Verifying failure...")
        try:
            # We call log_api_usage.
            # Note: Before the fix, log_api_usage sets timestamp manually.
            # This shouldn't affect the ID error, but we expect an IntegrityError on ID.
            database.log_api_usage("gemini", "test_fail", 1, 1, 100)
            self.fail("Should have raised IntegrityError due to missing ID")
        except Exception as e:
            print(f"Caught expected error: {e}")
            if "NOT NULL constraint failed: api_usage.id" not in str(e) and "integrity error" not in str(e).lower():
                 print(f"Warning: Unexpected error message: {e}")

        # 3. Run migration
        # This function must be added to src/database.py
        if not hasattr(database, 'migrate_api_usage_table'):
            self.fail("migrate_api_usage_table not found in database module")

        print("Running migration...")
        database.migrate_api_usage_table()

        # 4. Verify insertion works now
        print("Verifying success after migration...")
        try:
            database.log_api_usage("gemini_success", "test_success", 2, 2, 200)
        except Exception as e:
            self.fail(f"Insertion failed after migration: {e}")

        # 5. Verify data preservation and new data
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, api_name, calls FROM api_usage ORDER BY id")).fetchall()
            for row in rows:
                print(row)

            # We expect the 'existing_data' (id 999) and 'gemini_success' (new auto id)
            names = [r.api_name for r in rows]
            self.assertIn('existing_data', names)
            self.assertIn('gemini_success', names)

            # Verify that we have 2 rows
            self.assertEqual(len(rows), 2)

if __name__ == '__main__':
    unittest.main()
