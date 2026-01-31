import unittest
import sqlite3
import threading
import datetime
from database import get_db_connection

class TestIssue51(unittest.TestCase):
    def setUp(self):
        # Setup a clean state or use temporary table
        pass

    def test_timestamp_converter_in_new_thread(self):
        """
        Verify that the timestamp converter works correctly in a new thread.
        This reproduces the scenario where a new connection is created in a thread
        and needs the adapters to be registered.
        """
        def run_test(result_container):
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    # Create a temp table to avoid messing with real data
                    cursor.execute("CREATE TEMPORARY TABLE IF NOT EXISTS test_issue_51 (ts TIMESTAMP)")
                    cursor.execute("DELETE FROM test_issue_51")

                    # Insert a date-only string (raw)
                    conn.execute("INSERT INTO test_issue_51 (ts) VALUES (?)", ("2023-10-27",))
                    conn.commit()

                    # Read back
                    cursor.execute("SELECT ts FROM test_issue_51")
                    row = cursor.fetchone()
                    val = row['ts']

                    result_container['val'] = val
                    result_container['type'] = type(val)
            except Exception as e:
                result_container['error'] = e

        result = {}
        t = threading.Thread(target=run_test, args=(result,))
        t.start()
        t.join()

        if 'error' in result:
            self.fail(f"Thread failed with error: {result['error']}")

        self.assertIsInstance(result.get('val'), datetime.datetime,
                              f"Expected datetime object, got {result.get('type')}: {result.get('val')}")
        # Check that date-only was converted to midnight
        self.assertEqual(result['val'].hour, 0)
        self.assertEqual(result['val'].minute, 0)
        self.assertEqual(result['val'].second, 0)

if __name__ == '__main__':
    unittest.main()
