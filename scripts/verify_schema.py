import sqlite3
DB_PATH = "database/polymarket.db"

def verify():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check columns
    cursor.execute("PRAGMA table_info(active_bets)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(f"Active Bets Columns: {columns}")

    required = ['parent_event_slug', 'outcome_variant_id', 'is_multi_outcome']
    missing = [c for c in required if c not in columns]
    if missing:
        print(f"FAILED: Missing columns in active_bets: {missing}")
    else:
        print("SUCCESS: active_bets has new columns.")

    cursor.execute("PRAGMA table_info(archived_bets)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(f"Archived Bets Columns: {columns}")
    missing = [c for c in required if c not in columns]
    if missing:
        print(f"FAILED: Missing columns in archived_bets: {missing}")
    else:
        print("SUCCESS: archived_bets has new columns.")

    # Check Unique Constraint Removal on active_bets.market_slug
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='active_bets'")
    sql = cursor.fetchone()['sql']
    print(f"Active Bets SQL: {sql}")

    # Simple string check (robust parsing is hard, but we know what we wrote)
    if "market_slug TEXT NOT NULL UNIQUE" in sql:
         print("FAILED: market_slug is still UNIQUE in SQL definition")
    elif "UNIQUE (market_slug)" in sql:
         print("FAILED: market_slug is still UNIQUE via constraint")
    else:
         print("SUCCESS: market_slug is NOT UNIQUE")

    conn.close()

if __name__ == "__main__":
    verify()
