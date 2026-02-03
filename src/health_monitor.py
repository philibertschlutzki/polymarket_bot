import datetime
import logging
import os
import time
from typing import Dict, List

import psutil

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors system health, memory usage, and API metrics.
    """

    def __init__(
        self,
        memory_warning_threshold_mb: int = 400,
        memory_critical_threshold_mb: int = 480,
        export_path: str = "HEALTH_STATUS.md",
        max_history_size: int = 60,
    ):
        self.memory_warning_threshold_mb = memory_warning_threshold_mb
        self.memory_critical_threshold_mb = memory_critical_threshold_mb
        self.export_path = export_path
        self.max_history_size = max_history_size

        self.start_time = time.time()
        self.metrics_history: List[Dict] = []
        self.process = psutil.Process(os.getpid())

    def collect_metrics(
        self, rate_limiter_stats: Dict, queue_stats: Dict
    ) -> Dict:
        """Collects current system and application metrics."""

        # System Resources
        memory_info = self.process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        cpu_percent = self.process.cpu_percent(interval=None)  # Non-blocking if called repeatedly

        uptime_seconds = int(time.time() - self.start_time)
        uptime_str = str(datetime.timedelta(seconds=uptime_seconds))

        # Check Alerts
        alert_status = "OK"
        if memory_mb > self.memory_critical_threshold_mb:
            alert_status = "CRITICAL"
            logger.error(f"🚨 CRITICAL MEMORY USAGE: {memory_mb:.2f} MB")
        elif memory_mb > self.memory_warning_threshold_mb:
            alert_status = "WARNING"
            logger.warning(f"⚠️ HIGH MEMORY USAGE: {memory_mb:.2f} MB")

        current_metrics = {
            "timestamp": datetime.datetime.now().isoformat(),
            "uptime": uptime_str,
            "memory_mb": round(memory_mb, 2),
            "cpu_percent": cpu_percent,
            "alert_status": alert_status,
            "api": rate_limiter_stats,
            "queue": queue_stats,
        }

        self.metrics_history.append(current_metrics)
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history.pop(0)

        return current_metrics

    def log_heartbeat(self, metrics: Dict):
        """Logs a heartbeat message."""
        mem = metrics["memory_mb"]
        cpu = metrics["cpu_percent"]
        rpm = metrics["api"]["current_rpm"]
        success_rate = metrics["api"]["success_rate"]
        q_pending = metrics["queue"]["pending"]
        q_retries = metrics["queue"]["retry_queue_total"]
        uptime = metrics["uptime"]

        logger.info(
            f"💓 HEARTBEAT | Mem: {mem}MB | CPU: {cpu}% | API: {rpm} RPM @ {success_rate}% | "
            f"Q: {q_pending} pending, {q_retries} retries | Up: {uptime}"
        )

    def get_average_metrics(self, window_minutes: int = 15) -> Dict:
        """Calculates averages over the last window_minutes."""
        if not self.metrics_history:
            return {}

        # Assuming metrics are collected every minute (approx)
        # Just take the last N entries
        count = min(len(self.metrics_history), window_minutes)
        recent = self.metrics_history[-count:]

        avg_mem = sum(m["memory_mb"] for m in recent) / count
        avg_cpu = sum(m["cpu_percent"] for m in recent) / count
        avg_success = sum(m["api"]["success_rate"] for m in recent) / count

        return {
            "avg_memory_mb": round(avg_mem, 2),
            "avg_cpu_percent": round(avg_cpu, 2),
            "avg_api_success_rate": round(avg_success, 2),
        }

    def export_health_dashboard(self, current_metrics: Dict):
        """Exports the health dashboard to a Markdown file."""
        try:
            averages = self.get_average_metrics(15)
            api = current_metrics["api"]
            queue = current_metrics["queue"]

            # Icons
            status_icon = "🟢"
            if current_metrics["alert_status"] == "WARNING":
                status_icon = "🟡"
            elif current_metrics["alert_status"] == "CRITICAL":
                status_icon = "🔴"

            last_429 = api.get("last_429_time") or "Never"
            backoff_status = "Active ⏳" if api.get("backoff_active") else "No ✅"

            markdown = f"""# 🏥 Polymarket Bot - System Health Status
**Last Updated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Status**: {status_icon} {current_metrics['alert_status']}

## 🤖 API Status
| Metric | Value |
|--------|-------|
| Current RPM | **{api['current_rpm']}** |
| Success Rate | {api['success_rate']}% |
| Requests (Tot/Succ/Fail) | {api['total_requests']} / {api['successful_requests']} / {api['failed_requests']} |
| Backoff Active | {backoff_status} |
| Last 429 Error | {last_429} |
| Tokens Available | {api['tokens_available']} |

## 📊 Queue Status
| Metric | Count |
|--------|-------|
| Pending | {queue['pending']} |
| Processing | {queue['processing']} |
| Completed | {queue['completed']} |
| Failed | {queue['failed']} |
| Retry Queue | {queue['retry_queue_total']} |
| Retry Exhausted | {queue['retry_exhausted']} |

## 💻 System Resources
| Metric | Value |
|--------|-------|
| Memory Usage | **{current_metrics['memory_mb']} MB** |
| CPU Usage | {current_metrics['cpu_percent']}% |
| Uptime | {current_metrics['uptime']} |

## 📈 Performance Trends (15 min avg)
- **Avg Memory**: {averages.get('avg_memory_mb', 0)} MB
- **Avg CPU**: {averages.get('avg_cpu_percent', 0)}%
- **Avg API Success**: {averages.get('avg_api_success_rate', 0)}%

## ⚠️ Alerts
"""
            if current_metrics["alert_status"] != "OK":
                markdown += (
                    f"- **{current_metrics['alert_status']}**: "
                    f"Memory usage is high ({current_metrics['memory_mb']} MB)\n"
                )

            if api.get("backoff_active"):
                markdown += f"- **WARNING**: API Backoff active until {api.get('backoff_until')}\n"

            if current_metrics["alert_status"] == "OK" and not api.get("backoff_active"):
                markdown += "- All systems nominal.\n"

            with open(self.export_path, "w", encoding="utf-8") as f:
                f.write(markdown)

        except Exception as e:
            logger.error(f"❌ Failed to export health dashboard: {e}")
