import database
from datetime import datetime

# Initialize DB to ensure table exists
database.init_database()

# Set dummy data for git_sync_state
with database.get_db_connection() as conn:
    conn.execute("UPDATE git_sync_state SET last_git_push = ?, pending_changes_count = 1 WHERE id = 1", (database.safe_timestamp(datetime.now()),))
    conn.commit()

try:
    print(f"Should push: {database.should_push_to_git()}")
    print("Function execution successful, imports are correct.")
except Exception as e:
    print(f"Function execution failed: {e}")
    import traceback
    traceback.print_exc()
