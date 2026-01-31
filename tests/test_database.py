import unittest
import sqlite3
import os
from datetime import datetime
from database import flexible_timestamp_converter, safe_timestamp, get_db_connection

class TestDatabase(unittest.TestCase):
    def test_flexible_timestamp_converter(self):
        # Bytes (SQLite default)
        self.assertIsInstance(flexible_timestamp_converter(b"2023-01-01 12:00:00"), datetime)

        # String
        self.assertIsInstance(flexible_timestamp_converter("2023-01-01 12:00:00"), datetime)

        # Date only (Issue #49) - Bytes
        dt = flexible_timestamp_converter(b"2023-01-01")
        self.assertEqual(dt.year, 2023)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.day, 1)
        self.assertEqual(dt.hour, 0)
        self.assertEqual(dt.minute, 0)
        self.assertEqual(dt.second, 0)

        # String Date only
        dt = flexible_timestamp_converter("2023-01-01")
        self.assertEqual(dt.year, 2023)
        self.assertEqual(dt.hour, 0)

        # Invalid
        self.assertIsNone(flexible_timestamp_converter(None))
        self.assertIsNone(flexible_timestamp_converter(b""))

    def test_safe_timestamp(self):
        # None
        self.assertIsNone(safe_timestamp(None))

        # Datetime
        dt = datetime(2023, 1, 1, 12, 0, 0)
        self.assertEqual(safe_timestamp(dt), "2023-01-01 12:00:00")

        # String
        self.assertEqual(safe_timestamp("2023-01-01 12:00:00"), "2023-01-01 12:00:00")

        # Date only string
        self.assertEqual(safe_timestamp("2023-01-01"), "2023-01-01 00:00:00")

    def test_db_connection_params(self):
        # Check connection works
        with get_db_connection() as conn:
            self.assertIsInstance(conn, sqlite3.Connection)
            # Check row factory
            self.assertEqual(conn.row_factory, sqlite3.Row)

if __name__ == '__main__':
    unittest.main()
