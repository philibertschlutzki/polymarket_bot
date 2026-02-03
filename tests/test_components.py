import os
import time
import unittest
import shutil
from src.adaptive_rate_limiter import AdaptiveRateLimiter
from src.market_queue import QueueManager
from src.health_monitor import HealthMonitor

class TestComponents(unittest.TestCase):
    def setUp(self):
        self.test_db = "data/test_queue.db"
        if os.path.exists("data"):
             shutil.rmtree("data") # clear data dir
        os.makedirs("data", exist_ok=True)

    def tearDown(self):
        if os.path.exists("data"):
             shutil.rmtree("data")

    def test_rate_limiter(self):
        print("\nTesting Rate Limiter...")
        limiter = AdaptiveRateLimiter(initial_rpm=60, max_rpm=60) # 1 per second

        # Should get a token immediately
        self.assertTrue(limiter.acquire_token(block=False))

        # Should not get another one immediately (if we were strict, but 60rpm = 1 per sec)
        # Actually implementation refills based on time.
        # current_rpm=60 -> 1 token/sec.
        # token starts at 60. So we have plenty.

        limiter = AdaptiveRateLimiter(initial_rpm=60, max_rpm=60)
        limiter.tokens = 0.5
        self.assertFalse(limiter.acquire_token(block=False))

        # Test 429 logic
        limiter.report_429_error(retry_after=1)
        self.assertTrue(limiter.current_rpm < 60)
        self.assertIsNotNone(limiter.backoff_until)

        # Verify block waits (mocking time.sleep would be better but this is integration smoke test)
        # We won't do actual blocking wait to save time.

    def test_queue_manager(self):
        print("\nTesting Queue Manager...")
        qm = QueueManager(db_path=self.test_db)

        market = {"market_slug": "test-1", "question": "Will I pass?"}

        # Add
        self.assertTrue(qm.add_market(market, 0.8))
        self.assertFalse(qm.add_market(market, 0.8)) # Duplicate

        # Pop
        popped = qm.pop_next_market()
        self.assertEqual(popped["market_slug"], "test-1")

        # Mark completed
        qm.mark_completed("test-1", "Done")
        stats = qm.get_queue_stats()
        self.assertEqual(stats["completed"], 1)

        # Retry logic
        market2 = {"market_slug": "test-2", "question": "Retry me"}
        qm.add_market(market2, 0.5)
        qm.pop_next_market() # Move to processing

        qm.move_to_retry_queue("test-2", "ERROR", "Failed")
        stats = qm.get_queue_stats()
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["retry_queue_total"], 1)

    def test_health_monitor(self):
        print("\nTesting Health Monitor...")
        hm = HealthMonitor(export_path="data/HEALTH.md")

        api_stats = {"current_rpm": 4, "success_rate": 100, "total_requests": 10, "successful_requests": 10, "failed_requests": 0, "tokens_available": 4.0}
        queue_stats = {"pending": 5, "processing": 1, "completed": 10, "failed": 0, "retry_queue_total": 0, "retry_exhausted": 0}

        metrics = hm.collect_metrics(api_stats, queue_stats)
        self.assertIn("memory_mb", metrics)

        hm.export_health_dashboard(metrics)
        self.assertTrue(os.path.exists("data/HEALTH.md"))

if __name__ == "__main__":
    unittest.main()
