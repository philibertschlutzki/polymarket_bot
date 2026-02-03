import datetime
import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AdaptiveRateLimiter:
    """
    Token bucket rate limiter with dynamic RPM adjustment based on API responses.
    """

    def __init__(
        self,
        initial_rpm: float = 4.0,
        min_rpm: float = 1.0,
        max_rpm: float = 4.0,
        recovery_threshold: int = 10,
    ):
        self.initial_rpm = initial_rpm
        self.min_rpm = min_rpm
        self.max_rpm = max_rpm
        self.recovery_threshold = recovery_threshold

        # State Variables
        self.current_rpm = initial_rpm
        self.tokens = self.current_rpm  # Start full
        self.last_refill = time.time()
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.consecutive_successes = 0
        self.consecutive_failures = 0
        self.backoff_until: Optional[float] = None  # Timestamp
        self.last_429_time: Optional[float] = None  # Timestamp

        self.lock = threading.Lock()

    def _refill_tokens(self):
        """Refills tokens based on time elapsed."""
        now = time.time()
        elapsed = now - self.last_refill

        tokens_to_add = elapsed * (self.current_rpm / 60.0)
        self.tokens = min(self.tokens + tokens_to_add, self.max_rpm)
        self.last_refill = now

    def acquire_token(self, block: bool = True) -> bool:
        """
        Attempts to acquire a token.
        If block is True, waits until a token is available.
        """
        while True:
            sleep_time = 0.0
            with self.lock:
                now = time.time()
                # 1. Check Backoff
                if self.backoff_until:
                    if now < self.backoff_until:
                        if block:
                            sleep_time = self.backoff_until - now
                        else:
                            return False
                    else:
                        # Backoff expired
                        self.backoff_until = None

                # 2. If no backoff, try to acquire token
                if sleep_time == 0.0:
                    self._refill_tokens()

                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        self.total_requests += 1
                        return True

                    if not block:
                        return False

                    # Calculate wait time for token refill
                    tokens_needed = 1.0 - self.tokens
                    tokens_per_second = self.current_rpm / 60.0
                    if tokens_per_second > 0:
                        wait_time = tokens_needed / tokens_per_second
                        sleep_time = max(0.1, wait_time) # Minimum wait
                    else:
                        sleep_time = 1.0

            # Sleep outside the lock
            if sleep_time > 0:
                if self.backoff_until and sleep_time > 1.0:
                     logger.warning(f"⏳ Rate Limit Wait: Sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

    def report_success(self):
        """Called after a successful API request."""
        with self.lock:
            self.successful_requests += 1
            self.consecutive_successes += 1
            self.consecutive_failures = 0

            # Recovery logic
            if (
                self.consecutive_successes >= self.recovery_threshold
                and self.current_rpm < self.max_rpm
            ):
                self.current_rpm += 1.0
                self.consecutive_successes = 0
                logger.info(f"📈 API Health Good: Increasing RPM to {self.current_rpm}")

    def report_429_error(self, retry_after: int = 120):
        """Called after a 429 Resource Exhausted error."""
        with self.lock:
            self.failed_requests += 1
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.last_429_time = time.time()

            # Reduce RPM
            old_rpm = self.current_rpm
            self.current_rpm = max(self.current_rpm / 2.0, self.min_rpm)

            # Set backoff
            self.backoff_until = time.time() + retry_after

            # Drain tokens
            self.tokens = 0.0

            logger.error(
                f"🚨 Rate Limit Hit (429)! Reduced RPM: {old_rpm} -> {self.current_rpm}. Backoff {retry_after}s."
            )

    def report_error(self, error_type: str):
        """Called after a non-429 error."""
        with self.lock:
            self.failed_requests += 1
            logger.debug(f"⚠️ API Error: {error_type}")

    def get_stats(self) -> Dict:
        """Returns current statistics."""
        with self.lock:
            # Update tokens for accurate display
            self._refill_tokens()

            success_rate = 0.0
            if self.total_requests > 0:
                success_rate = (self.successful_requests / self.total_requests) * 100

            backoff_active = False
            backoff_until_str = None
            if self.backoff_until:
                 if time.time() < self.backoff_until:
                     backoff_active = True
                     backoff_until_str = datetime.datetime.fromtimestamp(self.backoff_until).isoformat()

            last_429_str = None
            if self.last_429_time:
                last_429_str = datetime.datetime.fromtimestamp(self.last_429_time).isoformat()

            return {
                "current_rpm": self.current_rpm,
                "tokens_available": round(self.tokens, 2),
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate": round(success_rate, 2),
                "consecutive_successes": self.consecutive_successes,
                "backoff_active": backoff_active,
                "backoff_until": backoff_until_str,
                "last_429_time": last_429_str,
            }

    def reset_stats(self):
        with self.lock:
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.consecutive_successes = 0
            self.consecutive_failures = 0
