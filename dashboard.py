import logging
import os
from datetime import datetime, timezone, timedelta
import asciichartpy
from dateutil import parser
import database
import math

logger = logging.getLogger(__name__)

# Try to get CET timezone
try:
    from zoneinfo import ZoneInfo
    CET_TZ = ZoneInfo("Europe/Berlin")
except ImportError:
    # Fallback to fixed offset (UTC+1) if zoneinfo is not available
    # Note: This does not handle DST automatically, but is a reasonable fallback
    CET_TZ = timezone(timedelta(hours=1))

def to_cet(dt):
    """Converts a datetime to CET/CEST."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = parser.parse(dt)
        except:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(CET_TZ)

def should_update_dashboard() -> bool:
    """
    Checks if the dashboard needs an update.
    Legacy function, kept for compatibility if needed,
    but main.py now calls generate_dashboard directly.
    """
    return True

def generate_dashboard():
    """Generates the complete Performance Dashboard."""
    logger.info("Generating dashboard...")

    # 1. Load Data
    capital = database.get_current_capital()
    metrics = database.calculate_metrics()
    active_bets = database.get_active_bets()
    results = database.get_all_results()
    last_run = database.get_last_run_timestamp()

    # Current time
    now_cet = datetime.now(CET_TZ)

    # === HEADER ===
    total_return_usd = metrics['total_return_usd']
    total_return_pct = metrics['total_return_percent'] * 100

    header = f"""# 📊 Polymarket AI Bot - Performance Dashboard

**Last Updated:** {now_cet.strftime('%Y-%m-%d %H:%M:%S %Z')}
**Current Capital:** ${capital:,.2f} USDC
**Total Return:** {total_return_pct:+.2f}% (${total_return_usd:+.2f})

---
"""

    # === SYSTEM STATUS ===
    # Next run is last_run + 15 mins
    if last_run:
        last_run_cet = to_cet(last_run)
        next_run_cet = last_run_cet + timedelta(minutes=15)
        time_until_next = (next_run_cet - now_cet).total_seconds()

        if time_until_next > 0:
            bot_status = "🟢 Active"
        elif time_until_next > -60:
            bot_status = "🟡 Running"
        else:
            bot_status = "🔴 Delayed"

        last_run_str = last_run_cet.strftime('%Y-%m-%d %H:%M:%S %Z')
        next_run_str = next_run_cet.strftime('%Y-%m-%d %H:%M:%S %Z')
    else:
        bot_status = "⚪ Unknown"
        last_run_str = "N/A"
        next_run_str = "N/A"

    system_status = f"""## ⏰ System Status

| Metric | Value |
|--------|-------|
| Last Run | {last_run_str} |
| Next Run | {next_run_str} |
| Run Interval | 15 minutes |
| Bot Status | {bot_status} |

---
"""

    # === GEMINI API USAGE ===
    rpm = database.get_api_usage_rpm("gemini")
    rpd = database.get_api_usage_rpd("gemini")
    tpm = database.get_api_usage_tpm("gemini")

    # Limits (Free Tier)
    LIMIT_RPM = 15
    LIMIT_RPD = 1500
    LIMIT_TPM = 1000000

    rpm_pct = (rpm / LIMIT_RPM) * 100
    rpd_pct = (rpd / LIMIT_RPD) * 100
    tpm_pct = (tpm / LIMIT_TPM) * 100

    def usage_indicator(pct):
        if pct >= 90: return "🔴"
        elif pct >= 70: return "🟡"
        else: return "🟢"

    gemini_usage = f"""## 🤖 Gemini API Usage

| Period | Calls/Tokens | Limit | Usage | Status |
|--------|--------------|-------|-------|--------|
| Current Minute (RPM) | {rpm} | {LIMIT_RPM} | {rpm_pct:.0f}% | {usage_indicator(rpm_pct)} |
| Today (RPD) | {rpd} | {LIMIT_RPD:,} | {rpd_pct:.1f}% | {usage_indicator(rpd_pct)} |
| Current Minute (TPM) | {tpm:,} | {LIMIT_TPM:,} | {tpm_pct:.2f}% | {usage_indicator(tpm_pct)} |

---
"""

    # === PERFORMANCE METRICS ===
    wins = sum(1 for r in results if r['profit_loss'] > 0)
    losses = len(results) - wins

    performance_metrics = f"""## 📈 Performance Metrics

| Metric | Value |
|--------|-------|
| Total Bets | {len(results)} |
| Win Rate | {metrics['win_rate']*100:.2f}% ({wins}W / {losses}L) |
| Avg ROI per Bet | {metrics['avg_roi']*100:+.1f}% |
| Sharpe Ratio | {metrics['sharpe_ratio']:.2f} |
| Max Drawdown | {metrics['max_drawdown']*100:.1f}% |
| Best Bet | ${metrics['best_bet_usd']:+.2f} |
| Worst Bet | ${metrics['worst_bet_usd']:+.2f} |

---
"""

    # === PORTFOLIO RISK METRICS ===
    total_exposure = sum(b['stake_usdc'] for b in active_bets)
    exposure_pct = (total_exposure / capital * 100) if capital > 0 else 0
    avg_position = total_exposure / len(active_bets) if active_bets else 0

    largest_stake = max((b['stake_usdc'] for b in active_bets), default=0)
    largest_pct = (largest_stake / capital * 100) if capital > 0 else 0

    # Concentration (HHI)
    if total_exposure > 0:
        stakes = [b['stake_usdc'] for b in active_bets]
        hhi = sum((s/total_exposure)**2 for s in stakes)
    else:
        hhi = 0

    if hhi < 0.15: concentration = "Low 🟢"
    elif hhi < 0.25: concentration = "Medium 🟡"
    else: concentration = "High 🔴"

    risk_metrics = f"""## ⚖️ Portfolio Risk Metrics

| Metric | Value |
|--------|-------|
| Total Exposure | ${total_exposure:.2f} ({exposure_pct:.1f}% of capital) |
| Avg Position Size | ${avg_position:.2f} |
| Largest Position | ${largest_stake:.2f} ({largest_pct:.1f}%) |
| Portfolio Concentration | {concentration} (HHI: {hhi:.3f}) |

---
"""

    # === ACTIVE BETS ===
    active_rows = []

    for bet in active_bets:
        q = bet['question']
        if len(q) > 40: q = q[:40] + "..."

        stake = bet['stake_usdc']
        price = bet['entry_price']
        ai_prob = bet['ai_probability'] if bet['ai_probability'] is not None else 0.0
        edge = bet['edge'] if bet['edge'] is not None else 0.0
        conf = bet['confidence_score'] if bet['confidence_score'] is not None else 0.0
        ev = bet['expected_value']

        # Edge Indicator
        if edge >= 0.20:
            edge_ind = "🟢"
        elif edge >= 0.10:
            edge_ind = "🟡"
        else:
            edge_ind = "🔴"

        # End Date
        # Use .get() or check keys to be safe against schema mismatches if migration failed
        end_date_raw = bet['end_date'] if 'end_date' in bet.keys() else None
        end_date_display = "Unknown"
        days_display = "N/A"
        status = "🔵"

        if end_date_raw:
            try:
                ed_cet = to_cet(end_date_raw)
                if ed_cet:
                    days_left = (ed_cet - now_cet).days

                    end_date_display = ed_cet.strftime('%Y-%m-%d')
                    days_display = f"{days_left}d"

                    if days_left < 0: status = "⏰ Expired"
                    elif days_left < 3: status = "🔴"
                    elif days_left < 7: status = "🟡"
                    else: status = "🟢"
            except:
                pass

        active_rows.append(
            f"| {q} | {bet['action']} | ${stake:.2f} | {price:.2f} | {ai_prob:.2f} | {edge:+.0%} {edge_ind} | {conf:.0%} | ${ev:+.2f} | {end_date_display} | {days_display} | {status} |"
        )

    active_table = "\n".join(active_rows) if active_rows else "| *No active bets* | - | - | - | - | - | - | - | - | - | - |"

    active_bets_section = f"""## 🎯 Active Bets ({len(active_bets)})

| Question | Action | Stake | Market | AI Prob | Edge | Conf | EV | End Date | Days Left | Status |
|---|---|---|---|---|---|---|---|---|---|---|
{active_table}

📊 **[View Detailed AI Analysis →](AI_DECISIONS.md)**

---
"""

    # === ALERTS / WARNINGS ===
    alerts = []
    if rpm_pct >= 90: alerts.append(f"🔴 **API Limit Warning**: Gemini RPM at {rpm_pct:.0f}% capacity")
    if rpd_pct >= 90: alerts.append(f"🔴 **API Limit Warning**: Gemini RPD at {rpd_pct:.0f}% capacity")
    if tpm_pct >= 90: alerts.append(f"🔴 **API Limit Warning**: Gemini TPM at {tpm_pct:.0f}% capacity")

    # High Exposure Alerts
    for bet in active_bets:
        pos_pct = (bet['stake_usdc'] / capital * 100) if capital > 0 else 0
        if pos_pct > 10:
             alerts.append(f"🔴 **High Exposure**: \"{bet['question'][:30]}...\" is {pos_pct:.1f}% of capital")

    # Expiring Soon Alerts
    expiring_soon = 0
    for bet in active_bets:
        if 'end_date' in bet.keys() and bet['end_date']:
            try:
                ed_cet = to_cet(bet['end_date'])
                if ed_cet:
                    days = (ed_cet - now_cet).days
                    if 0 <= days <= 7:
                        expiring_soon += 1
            except: pass

    if expiring_soon > 0:
        alerts.append(f"🟡 **Expiring Soon**: {expiring_soon} bet(s) expire within 7 days")

    if not alerts:
        alerts.append("🟢 **No critical issues detected**")

    alerts_section = f"""## ⚠️ Alerts & Warnings

{chr(10).join(f"- {a}" for a in alerts)}

---
"""

    # === MARKET INSIGHTS ===
    markets_analyzed = os.getenv("TOP_MARKETS_TO_ANALYZE", "15") # config

    markets_with_bets = len(active_bets)

    # Count recent rejections (last run)
    recent_rejections = database.get_rejected_markets(limit=20)  # Last run could be ~15 markets
    rejection_counts = {}
    for rej in recent_rejections:
        reason = rej['rejection_reason']
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    top_rejection = max(rejection_counts.items(), key=lambda x: x[1])[0] if rejection_counts else "N/A"

    market_insights = f"""## 📊 Market Insights

| Metric | Value |
|--------|-------|
| Markets Analyzed per Run | {markets_analyzed} |
| Markets with Active Bets | {markets_with_bets} |
| Markets Rejected (Last Run) | {len(recent_rejections)} |
| Top Rejection Reason | {top_rejection} |

📋 **[View All Rejected Markets →](AI_DECISIONS.md#rejected-markets)**

---
"""

    # === CAPITAL CHART & RESULTS ===
    chart_section = generate_chart_section(results)
    recent_section = generate_recent_results_section(results)

    # === ADVANCED ANALYTICS ===
    advanced_analytics_section = generate_advanced_analytics_section(results)

    # Assembly
    content = (
        header +
        system_status +
        gemini_usage +
        performance_metrics +
        risk_metrics +
        active_bets_section +
        alerts_section +
        market_insights +
        advanced_analytics_section +  # NEU
        chart_section +
        recent_section
    )

    content += "\n*Generated by Polymarket AI Bot v2.0*\n"

    with open('PERFORMANCE_DASHBOARD.md', 'w', encoding='utf-8') as f:
        f.write(content)

    database.update_last_dashboard_update()
    logger.info("✅ Dashboard generated successfully.")

def generate_advanced_analytics_section(results: list) -> str:
    """Generiert erweiterte Analytics Section."""

    if len(results) < 5:
        return """## 📊 Advanced Analytics

*Insufficient data (need at least 5 closed bets)*

---
"""

    import analytics_advanced

    # 1. Confidence Calibration
    calibration = analytics_advanced.calculate_confidence_calibration(results)

    calibration_section = """## 🎯 AI Confidence Calibration

| Confidence Range | Predicted | Actual | Bets | Error | Status |
|------------------|-----------|--------|------|-------|--------|
"""

    for bucket in calibration['buckets']:
        if bucket['num_bets'] == 0:
            calibration_section += f"| {bucket['range']} | - | - | 0 | - | Insufficient data |\n"
        else:
            pred = f"{bucket['predicted_win_rate']:.1%}"
            actual = f"{bucket['actual_win_rate']:.1%}" if bucket['actual_win_rate'] else "N/A"
            error = f"{bucket['calibration_error']:+.1%}" if bucket['calibration_error'] else "N/A"

            # Status icon
            if bucket['status'] == 'well_calibrated':
                icon = "✅"
            elif bucket['status'] == 'acceptable':
                icon = "⚠️"
            elif bucket['status'] == 'overconfident':
                icon = "🔴"
            elif bucket['status'] == 'underconfident':
                icon = "🔵"
            else:
                icon = "⚪"

            calibration_section += f"| {bucket['range']} | {pred} | {actual} | {bucket['num_bets']} | {error} | {icon} {bucket['status'].replace('_', ' ').title()} |\n"

    overall = calibration['overall_calibration']
    calibration_section += f"\n**Overall Calibration Score:** {overall:.1%} "

    if overall >= 0.90:
        calibration_section += "🟢 Excellent\n"
    elif overall >= 0.80:
        calibration_section += "🟡 Good\n"
    else:
        calibration_section += "🔴 Needs improvement\n"

    # 2. Edge Validation
    edge_val = analytics_advanced.calculate_edge_validation(results, min_bets=10)

    edge_section = """\n## 📐 Edge Validation Analysis

| Predicted Edge | Avg Pred | Avg Real | Delta | Accuracy | Bets |
|----------------|----------|----------|-------|----------|------|
"""

    for bucket in edge_val['buckets']:
        if bucket['status'] == 'insufficient_data':
            edge_section += f"| {bucket['range']} | - | - | - | - | {bucket['num_bets']} (need 10+) |\n"
        else:
            pred = f"{bucket['avg_predicted_edge']:+.1%}"
            real = f"{bucket['avg_realized_edge']:+.1%}"
            delta = f"{bucket['delta']:+.1%}"
            acc = f"{bucket['accuracy']:.0%}"

            # Accuracy icon
            if bucket['accuracy'] >= 0.90:
                acc_icon = "✅"
            elif bucket['accuracy'] >= 0.80:
                acc_icon = "⚠️"
            else:
                acc_icon = "🔴"

            edge_section += f"| {bucket['range']} | {pred} | {real} | {delta} | {acc} {acc_icon} | {bucket['num_bets']} |\n"

    edge_section += f"\n**Overall Edge Accuracy:** {edge_val['overall_accuracy']:.0%}\n"

    # 3. AI Model Trends
    trends = analytics_advanced.calculate_model_trends(results, window_days=30, num_periods=8)

    trends_section = """\n## 📈 AI Model Performance Trends (30-day Rolling)

| Period | Win Rate | Avg Conf | Calibration | Bets |
|--------|----------|----------|-------------|------|
"""

    for period in trends['periods']:
        trends_section += (
            f"| {period['period_label']} | "
            f"{period['win_rate']:.1%} | "
            f"{period['avg_confidence']:.0%} | "
            f"{period['calibration_score']:.0%} | "
            f"{period['num_bets']} |\n"
        )

    # Trend indicator
    trend_icons = {
        'improving': '📈 Improving',
        'declining': '📉 Declining',
        'stable': '➡️ Stable',
        'insufficient_data': '⚪ Insufficient data'
    }

    trends_section += f"\n**Trend:** {trend_icons.get(trends['trend_direction'], 'Unknown')}\n"

    # 4. Drawdown Analysis
    capital_history = database.get_capital_history()
    dd_metrics = analytics_advanced.calculate_drawdown_metrics(capital_history)

    if dd_metrics.get('status') == 'insufficient_data':
        dd_section = "\n## 📉 Drawdown Analysis\n\n*Insufficient data*\n"
    else:
        # Status emoji
        status_icons = {
            'normal': '🟢',
            'warning': '🟡',
            'alert': '🟠',
            'critical': '🔴'
        }

        status_icon = status_icons.get(dd_metrics['status'], '⚪')

        dd_section = f"""
## 📉 Drawdown Analysis

### Current Status: {status_icon} {dd_metrics['status'].upper()}

| Metric | Value |
|--------|-------|
| Current Drawdown | {dd_metrics['current_drawdown_pct']:.2%} |
| Days in Drawdown | {dd_metrics['current_drawdown_days']} days |
| Peak Capital | ${dd_metrics['peak_capital']:.2f} |
| Current Capital | ${dd_metrics['current_capital']:.2f} |
| Max Historical DD | {dd_metrics['max_historical_dd']:.2%} |
| Max DD Recovery Time | {dd_metrics['max_dd_recovery_days']} days |

**Recommendation:** {dd_metrics['recommendation']}

"""

        if dd_metrics['drawdown_periods']:
            dd_section += "### Historical Drawdown Periods\n\n"
            dd_section += "| Start | End | Duration | Max DD | Recovery |\n"
            dd_section += "|-------|-----|----------|--------|----------|\n"

            for period in dd_metrics['drawdown_periods'][:3]:  # Top 3
                dd_section += (
                    f"| {period['start_date']} | "
                    f"{period['end_date']} | "
                    f"{period['duration_days']}d | "
                    f"{period['max_dd']:.2%} | "
                    f"{period['recovery_days']}d |\n"
                )

    # Combine all sections
    return (
        calibration_section +
        edge_section +
        trends_section +
        dd_section +
        "\n---\n"
    )

def generate_chart_section(results):
    capital_history = [database.INITIAL_CAPITAL]
    running = database.INITIAL_CAPITAL
    sorted_res = sorted(results, key=lambda x: x['timestamp_closed'])
    for r in sorted_res:
        running += r['profit_loss']
        capital_history.append(running)

    chart_data = capital_history[-30:]
    if len(chart_data) >= 2:
        try:
            chart = asciichartpy.plot(chart_data, {'height': 10})
        except:
            chart = "Error generating chart."
    else:
        chart = "Insufficient data for chart (need at least 2 data points)."

    return f"""## 📊 Capital Performance (ASCII Chart)

```
{chart}
```

---
"""

def generate_recent_results_section(results):
    recent = sorted(results, key=lambda x: x['timestamp_closed'], reverse=True)[:10]
    if not recent:
        return """## 📜 Recent Results (Last 10)

*No results yet.*

---
"""

    rows = []
    for r in recent:
        ts = r['timestamp_closed']
        ts_cet = to_cet(ts)
        date_str = ts_cet.strftime('%Y-%m-%d') if ts_cet else "N/A"
        icon = "✅ WIN" if r['profit_loss'] > 0 else "❌ LOSS"
        rows.append(f"| {date_str} | {r['question']} | {r['action']} | {icon} | ${r['profit_loss']:+.2f} |")

    return f"""## 📜 Recent Results (Last 10)

| Date | Question | Action | Outcome | P&L |
|---|---|---|---|---|
{chr(10).join(rows)}

---
"""

if __name__ == "__main__":
    generate_dashboard()
