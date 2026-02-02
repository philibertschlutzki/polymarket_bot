"""
Generate detailed API usage reports for debugging.
"""

import os
import sys
from datetime import datetime, timezone

# Add project root to sys.path to allow imports from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import database  # noqa: E402


def generate_api_usage_report():
    """Generate detailed API usage report."""

    now = datetime.now(timezone.utc)

    # Current metrics
    rpm = database.get_api_usage_rpm("gemini")
    rpd = database.get_api_usage_rpd("gemini")
    tpm = database.get_api_usage_tpm("gemini")

    # Calculate usage percentages (using constants from requirements)
    GEMINI_RPM_LIMIT = 15
    GEMINI_RPD_LIMIT = 1500
    GEMINI_TPM_LIMIT = 1_000_000

    rpm_pct = (rpm / GEMINI_RPM_LIMIT) * 100
    rpd_pct = (rpd / GEMINI_RPD_LIMIT) * 100
    tpm_pct = (tpm / GEMINI_TPM_LIMIT) * 100

    # Status indicators
    rpm_status = '🔴 LIMIT' if rpm_pct >= 90 else '🟡 WARNING' if rpm_pct >= 70 else '🟢 OK'
    rpd_status = '🔴 LIMIT' if rpd_pct >= 90 else '🟡 WARNING' if rpd_pct >= 70 else '🟢 OK'
    tpm_status = '🔴 LIMIT' if tpm_pct >= 90 else '🟡 WARNING' if tpm_pct >= 70 else '🟢 OK'

    report = f"""
╔══════════════════════════════════════════════════════════════╗
║           GEMINI API USAGE REPORT                            ║
║  Generated: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}                      ║
╠══════════════════════════════════════════════════════════════╣
║  CURRENT MINUTE (RPM)                                        ║
║  Requests: {rpm:>4} / {GEMINI_RPM_LIMIT}       ({rpm_pct:>5.1f}%)                       ║
║  Tokens:   {tpm:>8,} / {GEMINI_TPM_LIMIT:,} ({tpm_pct:>5.2f}%)                  ║
╠══════════════════════════════════════════════════════════════╣
║  TODAY (RPD)                                                 ║
║  Requests: {rpd:>4} / {GEMINI_RPD_LIMIT:,}    ({rpd_pct:>5.1f}%)                       ║
╠══════════════════════════════════════════════════════════════╣
║  STATUS                                                      ║
║  RPM: {rpm_status:<50} ║
║  RPD: {rpd_status:<50} ║
║  TPM: {tpm_status:<50} ║
╚══════════════════════════════════════════════════════════════╝
    """

    print(report)
    return report


if __name__ == "__main__":
    generate_api_usage_report()
