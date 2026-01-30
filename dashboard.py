import logging
from datetime import datetime
import asciichartpy
import database

logger = logging.getLogger(__name__)

def should_update_dashboard() -> bool:
    """
    Checks if the dashboard needs an update.
    Returns True if there are new bets or results since the last update.
    """
    last_update = database.get_last_dashboard_update()

    if not last_update:
        return True

    # Get latest activity timestamps
    with database.get_db_connection() as conn:
        cursor = conn.cursor()

        # Check latest bet creation
        cursor.execute("SELECT MAX(timestamp_created) as last_bet FROM active_bets")
        last_bet = cursor.fetchone()['last_bet']

        # Check latest result
        cursor.execute("SELECT MAX(timestamp_closed) as last_result FROM results")
        last_result = cursor.fetchone()['last_result']

        # Parse timestamps if they are strings (depends on sqlite adapter)
        # Using database.get_last_dashboard_update logic (adapter might handle it, or we use parser)
        from dateutil import parser

        if isinstance(last_bet, str):
            last_bet = parser.parse(last_bet)
        if isinstance(last_result, str):
            last_result = parser.parse(last_result)

        if last_bet and last_bet > last_update:
            return True
        if last_result and last_result > last_update:
            return True

    return False

def generate_dashboard():
    """Generates the PERFORMANCE_DASHBOARD.md file."""
    try:
        metrics = database.calculate_metrics()
        current_capital = database.get_current_capital()
        active_bets = database.get_active_bets()
        results = database.get_all_results()

        # Formatting
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S CET")
        total_return_pct = f"{metrics['total_return_percent']*100:+.2f}%"
        total_return_usd = f"${metrics['total_return_usd']:+.2f}"

        win_rate_str = f"{metrics['win_rate']*100:.2f}%"
        wins = sum(1 for r in results if r['profit_loss'] > 0)
        losses = len(results) - wins
        win_rate_detail = f"({wins}W / {losses}L)"

        # Chart Data
        # Reconstruct capital history from results
        capital_history = [database.INITIAL_CAPITAL]
        running_cap = database.INITIAL_CAPITAL
        # Sort results by closed time
        sorted_results = sorted(results, key=lambda x: x['timestamp_closed'])
        for res in sorted_results:
            running_cap += res['profit_loss']
            capital_history.append(running_cap)

        # Limit to last 30 points for chart readability
        chart_data = capital_history[-30:]

        chart_str = ""
        if len(chart_data) >= 2:
            try:
                chart_str = asciichartpy.plot(chart_data, {'height': 10})
            except Exception as e:
                chart_str = f"Error generating chart: {e}"
        else:
            chart_str = "Insufficient data for chart (need at least 2 data points)."

        # Active Bets Table
        active_bets_md = ""
        if active_bets:
            active_bets_md = "| Question | Action | Stake | Entry Price | Expected Value | Days Open |\n"
            active_bets_md += "|---|---|---|---|---|---|\n"
            for bet in active_bets:
                # Calculate days open
                created = bet['timestamp_created']
                if isinstance(created, str):
                    from dateutil import parser
                    created = parser.parse(created)
                days_open = (datetime.now() - created).days

                active_bets_md += f"| {bet['question']} | {bet['action']} | ${bet['stake_usdc']:.2f} | {bet['entry_price']:.2f} | ${bet['expected_value']:+.2f} | {days_open} |\n"
        else:
            active_bets_md = "*No active bets.*"

        # Top 5 Best Bets
        sorted_by_profit = sorted(results, key=lambda x: x['profit_loss'], reverse=True)
        top_5_best = sorted_by_profit[:5]
        best_bets_md = ""
        if top_5_best:
            best_bets_md = "| Question | Action | ROI | Profit |\n|---|---|---|---|\n"
            for bet in top_5_best:
                best_bets_md += f"| {bet['question']} | {bet['action']} | {bet['roi']*100:+.1f}% | ${bet['profit_loss']:+.2f} |\n"
        else:
            best_bets_md = "*No closed bets yet.*"

        # Top 5 Worst Bets
        sorted_by_loss = sorted(results, key=lambda x: x['profit_loss']) # Ascending (negatives first)
        top_5_worst = sorted_by_loss[:5]
        worst_bets_md = ""
        if top_5_worst:
            worst_bets_md = "| Question | Action | ROI | Loss |\n|---|---|---|---|\n"
            for bet in top_5_worst:
                # Check if it's actually a loss or just least profit
                if bet['profit_loss'] < 0:
                     worst_bets_md += f"| {bet['question']} | {bet['action']} | {bet['roi']*100:+.1f}% | ${bet['profit_loss']:+.2f} |\n"

        if not worst_bets_md:
             worst_bets_md = "*No losing bets yet.*"

        # Recent Results (Last 10)
        recent_results = sorted_results[-10:][::-1] # Reverse to have newest first
        recent_md = ""
        if recent_results:
            recent_md = "| Date | Question | Action | Outcome | P&L |\n|---|---|---|---|---|\n"
            for bet in recent_results:
                closed_date = bet['timestamp_closed']
                if isinstance(closed_date, str):
                    from dateutil import parser
                    closed_date = parser.parse(closed_date)
                date_str = closed_date.strftime("%Y-%m-%d")

                outcome_icon = "✅ WIN" if bet['profit_loss'] > 0 else "❌ LOSS"
                recent_md += f"| {date_str} | {bet['question']} | {bet['action']} | {outcome_icon} | ${bet['profit_loss']:+.2f} |\n"
        else:
            recent_md = "*No results yet.*"

        # Markdown Assembly
        md_content = f"""# 📊 Polymarket AI Bot - Performance Dashboard

**Last Updated:** {timestamp}
**Current Capital:** ${current_capital:,.2f} USDC
**Total Return:** {total_return_pct} ({total_return_usd})

---

## 📈 Performance Metrics

| Metric | Value |
|--------|-------|
| Total Bets | {metrics['total_bets']} |
| Win Rate | {win_rate_str} {win_rate_detail} |
| Avg ROI per Bet | {metrics['avg_roi']*100:+.1f}% |
| Sharpe Ratio | {metrics['sharpe_ratio']:.2f} |
| Max Drawdown | {metrics['max_drawdown']*100:.1f}% |
| Best Bet | ${metrics['best_bet_usd']:+.2f} |
| Worst Bet | ${metrics['worst_bet_usd']:+.2f} |

---

## 🎯 Active Bets ({len(active_bets)})

{active_bets_md}

---

## 📊 Capital Performance (ASCII Chart)

```
{chart_str}
```

---

## 🏆 Top 5 Best Bets

{best_bets_md}

---

## 💀 Top 5 Worst Bets

{worst_bets_md}

---

## 📜 Recent Results (Last 10)

{recent_md}

---

*Generated by Polymarket AI Bot v2.0*
"""

        with open('PERFORMANCE_DASHBOARD.md', 'w') as f:
            f.write(md_content)

        database.update_last_dashboard_update()
        logger.info("✅ Dashboard generated successfully.")

    except Exception as e:
        logger.error(f"❌ Error generating dashboard: {e}", exc_info=True)

if __name__ == "__main__":
    generate_dashboard()
