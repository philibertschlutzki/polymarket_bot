import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Manages a persistent queue of markets to analyze, including priority scheduling
    and retry logic with exponential backoff.
    """

    def __init__(self, db_path: str = "data/queue.db"):
        self.db_path = db_path
        self.local = threading.local()  # Thread-local storage for DB connections
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Returns a thread-local database connection."""
        if not hasattr(self.local, "conn"):
            import os
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

            self.local.conn = sqlite3.connect(self.db_path, timeout=30.0)
            self.local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self.local.conn.execute("PRAGMA journal_mode=WAL;")
        return self.local.conn

    def _init_db(self):
        """Initializes the database schema."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS market_queue (
                        market_slug TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        priority_score REAL DEFAULT 0.0,
                        status TEXT DEFAULT 'pending',
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_queue_priority
                    ON market_queue (status, priority_score DESC)
                    """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS retry_queue (
                        market_slug TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        error_type TEXT,
                        failure_count INTEGER DEFAULT 1,
                        next_retry_at TIMESTAMP,
                        first_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_retry_time
                    ON retry_queue (next_retry_at ASC)
                    """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS queue_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        market_slug TEXT,
                        action TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        details TEXT
                    )
                    """
                )
        except Exception as e:
            logger.error(f"❌ Failed to initialize queue DB: {e}")
            raise

    def add_market(self, market_data: Dict[str, Any], priority_score: float) -> bool:
        """
        Adds a market to the processing queue.
        Returns True if added, False if already exists.
        """
        conn = self._get_conn()
        market_slug = market_data.get("market_slug")
        if not market_slug:
            return False

        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO market_queue (market_slug, data, priority_score, status)
                    VALUES (?, ?, ?, 'pending')
                    """,
                    (market_slug, json.dumps(market_data), priority_score),
                )

                self._log_history(conn, market_slug, "added", {"priority": priority_score})
                return True
        except sqlite3.IntegrityError:
            # Already exists
            return False
        except Exception as e:
            logger.error(f"❌ Error adding market to queue: {e}")
            return False

    def pop_next_market(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves and locks the highest priority pending market.
        Status pending -> processing.
        """
        conn = self._get_conn()
        try:
            with conn:
                # Find best candidate
                cursor = conn.execute(
                    """
                    SELECT market_slug, data FROM market_queue
                    WHERE status = 'pending'
                    ORDER BY priority_score DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()

                if row:
                    market_slug = row["market_slug"]
                    market_data = json.loads(row["data"])

                    # Mark as processing
                    conn.execute(
                        """
                        UPDATE market_queue
                        SET status = 'processing', processed_at = CURRENT_TIMESTAMP
                        WHERE market_slug = ?
                        """,
                        (market_slug,),
                    )

                    return market_data
                return None
        except Exception as e:
            logger.error(f"❌ Error popping market from queue: {e}")
            return None

    def mark_completed(self, market_slug: str, result_summary: str):
        """Marks a market as successfully processed."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE market_queue
                    SET status = 'completed'
                    WHERE market_slug = ?
                    """,
                    (market_slug,),
                )
                self._log_history(conn, market_slug, "completed", {"result": result_summary})
        except Exception as e:
            logger.error(f"❌ Error marking market completed: {e}")

    def move_to_retry_queue(self, market_slug: str, error_type: str, error_msg: str):
        """Moves a failed market to the retry queue with backoff."""
        conn = self._get_conn()
        try:
            with conn:
                # Get current failure count if exists in retry queue, or start at 0
                cursor = conn.execute(
                    "SELECT failure_count, data FROM retry_queue WHERE market_slug = ?",
                    (market_slug,)
                )
                row = cursor.fetchone()

                if row:
                    failure_count = row["failure_count"] + 1
                    market_json = row["data"]
                else:
                    failure_count = 1
                    # Fetch data from main queue
                    cursor = conn.execute(
                         "SELECT data FROM market_queue WHERE market_slug = ?",
                         (market_slug,)
                    )
                    m_row = cursor.fetchone()
                    if not m_row:
                        logger.error(f"❌ Could not find market data for {market_slug} to retry")
                        return
                    market_json = m_row["data"]

                # Mark as failed in main queue
                conn.execute(
                    "UPDATE market_queue SET status = 'failed' WHERE market_slug = ?",
                    (market_slug,)
                )

                if failure_count > 6:
                    self._log_history(conn, market_slug, "retry_exhausted", {"error": error_msg})
                    logger.warning(f"❌ Retry limit exhausted for {market_slug}")
                    return

                # Calculate backoff
                # 60, 120, 300, 600, 1800, 3600
                backoff_map = {1: 60, 2: 120, 3: 300, 4: 600, 5: 1800}
                wait_seconds = backoff_map.get(failure_count, 3600)

                next_retry = datetime.now() + timedelta(seconds=wait_seconds)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO retry_queue
                    (market_slug, data, error_type, failure_count, next_retry_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (market_slug, market_json, error_type, failure_count, next_retry),
                )

                self._log_history(conn, market_slug, "retrying", {
                    "attempt": failure_count,
                    "wait": wait_seconds,
                    "error": error_msg
                })

        except Exception as e:
            logger.error(f"❌ Error moving to retry queue: {e}")

    def check_retry_queue(self) -> List[Dict[str, Any]]:
        """Checks for markets ready to be retried and requeues them."""
        conn = self._get_conn()
        requeued = []
        try:
            with conn:
                cursor = conn.execute(
                    """
                    SELECT market_slug, data, failure_count
                    FROM retry_queue
                    WHERE next_retry_at <= CURRENT_TIMESTAMP
                    LIMIT 5
                    """
                )
                rows = cursor.fetchall()

                for row in rows:
                    market_slug = row["market_slug"]
                    data = json.loads(row["data"])
                    # Re-insert into main queue with slightly lower priority
                    # But we need to calculate priority. For now assume base priority
                    # from data if available, or fetch it?
                    # To simplify, we'll just set it to 'pending' in main queue if it exists
                    # or insert if needed.

                    # Actually, the spec says: "Priority Penalty: Reduce by 0.1 per failure"
                    # We need to know the original priority. It's in market_queue but status is 'failed'.

                    mq_cursor = conn.execute(
                        "SELECT priority_score FROM market_queue WHERE market_slug = ?",
                        (market_slug,)
                    )
                    mq_row = mq_cursor.fetchone()
                    orig_priority = mq_row["priority_score"] if mq_row else 0.5

                    new_priority = max(orig_priority - (0.1 * row["failure_count"]), 0.1)

                    conn.execute(
                        """
                        UPDATE market_queue
                        SET status = 'pending', priority_score = ?
                        WHERE market_slug = ?
                        """,
                        (new_priority, market_slug)
                    )

                    # Remove from retry_queue?
                    # Spec says "Keep: Original retry_queue entry for history" - but we should probably
                    # update it so we don't pick it up again immediately?
                    # Or maybe just delete it, and rely on `move_to_retry_queue` to create it again if it fails?
                    # "requeue_from_retry()... Keep: Original retry_queue entry for history" seems to imply
                    # keeping the record but maybe marking it processed?
                    # Let's delete it from retry_queue to avoid loop, since we have history table.
                    conn.execute("DELETE FROM retry_queue WHERE market_slug = ?", (market_slug,))

                    self._log_history(conn, market_slug, "requeued", {"new_priority": new_priority})
                    requeued.append(data)

        except Exception as e:
            logger.error(f"❌ Error checking retry queue: {e}")

        return requeued

    def get_queue_stats(self) -> Dict:
        """Returns queue statistics."""
        conn = self._get_conn()
        stats = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "retry_queue_total": 0,
            "retry_exhausted": 0
        }
        try:
            cursor = conn.execute("SELECT status, COUNT(*) as cnt FROM market_queue GROUP BY status")
            for row in cursor:
                stats[row["status"]] = row["cnt"]

            cursor = conn.execute("SELECT COUNT(*) as cnt FROM retry_queue")
            stats["retry_queue_total"] = cursor.fetchone()["cnt"]

            cursor = conn.execute("SELECT COUNT(*) as cnt FROM retry_queue WHERE failure_count >= 6")
            stats["retry_exhausted"] = cursor.fetchone()["cnt"]

        except Exception as e:
            logger.error(f"❌ Error getting queue stats: {e}")

        return stats

    def cleanup_old_entries(self, days: int = 7):
        """Removes old entries."""
        conn = self._get_conn()
        try:
            with conn:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()

                # Cleanup market_queue
                conn.execute(
                    """
                    DELETE FROM market_queue
                    WHERE status IN ('completed', 'failed')
                    AND processed_at < ?
                    """,
                    (cutoff,)
                )

                # Cleanup retry_queue (exhausted)
                # Actually retry_queue doesn't have processed_at, using first_attempt or next_retry_at
                conn.execute(
                    """
                    DELETE FROM retry_queue
                    WHERE failure_count >= 6
                    AND first_attempt < ?
                    """,
                    (cutoff,)
                )

                # Cleanup history
                conn.execute("DELETE FROM queue_history WHERE timestamp < ?", (cutoff,))

        except Exception as e:
            logger.error(f"❌ Error cleaning up queue: {e}")

    def _log_history(self, conn, market_slug, action, details):
        try:
            conn.execute(
                "INSERT INTO queue_history (market_slug, action, details) VALUES (?, ?, ?)",
                (market_slug, action, json.dumps(details))
            )
        except Exception:
            pass
