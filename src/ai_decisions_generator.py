import logging
from datetime import datetime

from src import database
from src.dashboard import CET_TZ, to_cet

logger = logging.getLogger(__name__)


def generate_ai_decisions_file():  # noqa: C901
    """Generates the AI Decision Log Markdown file.

    Compiles a detailed log of all AI-driven trading decisions, including active
    bets, rejected markets, and historical analysis. The output is written to
    `AI_DECISIONS.md` and includes full reasoning text from the Gemini API.
    """

    logger.info("Generating AI_DECISIONS.md...")

    now_cet = datetime.now(CET_TZ)

    # Load Data
    active_bets = database.get_active_bets()
    rejected_markets = database.get_rejected_markets(limit=100)  # Last 100
    closed_bets = database.get_all_results()

    # === HEADER ===
    header = f"""# 🧠 AI Decision Log

**Last Updated:** {now_cet.strftime('%Y-%m-%d %H:%M:%S %Z')}

This file contains detailed AI reasoning for all market analyses.

---

## 📑 Table of Contents
- [Active Bets](#active-bets)
- [Rejected Markets](#rejected-markets)
- [Historical Analysis](#historical-analysis)

---

"""

    # === ACTIVE BETS DETAILED ===
    active_section = "## 🎯 Active Bets\n\n"

    if not active_bets:
        active_section += "*No active bets.*\n\n"

    for i, bet in enumerate(active_bets, 1):
        # Access with fallback for safety if columns were just added and rows have NULL
        ai_prob = (
            bet["ai_probability"] if bet["ai_probability"] is not None else 0.0
        )
        conf = (
            bet["confidence_score"] if bet["confidence_score"] is not None else 0.0
        )
        edge = bet["edge"] if bet["edge"] is not None else 0.0
        reasoning = (
            bet["ai_reasoning"]
            if bet["ai_reasoning"] is not None
            else "No reasoning available"
        )

        # End Date
        end_date_str = "Unknown"
        if bet["end_date"]:
            try:
                ed_cet = to_cet(bet["end_date"])
                if ed_cet:
                    end_date_str = ed_cet.strftime("%Y-%m-%d %H:%M %Z")
            except Exception:
                pass

        active_section += f"""### Bet #{i}: {bet['question']}

**Decision:** {bet['action']} @ {bet['entry_price']:.2f} (Stake: ${bet['stake_usdc']:.2f})

**AI Analysis:**
- **Estimated Probability:** {ai_prob:.1%} (vs Market: {bet['entry_price']:.1%})
- **Confidence Score:** {conf:.1%}
- **Edge:** {edge:+.1%}
- **Expected Value:** ${bet['expected_value']:+.2f}
- **End Date:** {end_date_str}

**AI Reasoning:**
> {reasoning}

---

"""

    # === REJECTED MARKETS ===
    rejected_section = "## ❌ Rejected Markets\n\n"
    rejected_section += (
        f"*Showing last {len(rejected_markets)} rejected analyses*\n\n"
    )

    # Group by rejection reason
    rejection_groups = {}
    for rej in rejected_markets:
        reason = rej["rejection_reason"]
        if reason not in rejection_groups:
            rejection_groups[reason] = []
        rejection_groups[reason].append(rej)

    for reason, markets in rejection_groups.items():
        rejected_section += (
            f"### {reason.replace('_', ' ').title()} ({len(markets)})\n\n"
        )

        for market in markets[:10]:  # Max 10 per category
            ai_prob = (
                market["ai_probability"]
                if market["ai_probability"] is not None
                else 0.0
            )
            edge = market["edge"] if market["edge"] is not None else 0.0
            reasoning = (
                market["ai_reasoning"]
                if market["ai_reasoning"] is not None
                else "N/A"
            )
            conf = (
                market["confidence_score"]
                if market["confidence_score"] is not None
                else 0.0
            )

            timestamp = to_cet(market["timestamp_analyzed"])
            time_str = (
                timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Unknown"
            )

            rejected_section += f"""**{market['question'][:60]}...**
*Analyzed: {time_str}*
Market: {market['market_price']:.2f} | AI: {ai_prob:.2f} | Edge: {edge:+.1%} | Conf: {conf:.0%}
Reasoning: {reasoning[:150]}...

"""

        rejected_section += "\n"

    # === HISTORICAL ANALYSIS (ERWEITERT) ===
    history_section = "## 📊 Historical Analysis\n\n"

    if not closed_bets:
        history_section += "*No closed bets yet for analysis.*\n\n"
    else:
        from src import analytics_advanced

        # Confidence Calibration
        calibration = analytics_advanced.calculate_confidence_calibration(
            closed_bets
        )

        history_section += "### AI Confidence Calibration\n\n"
        history_section += (
            "Measures how well AI confidence scores match actual outcomes:\n\n"
        )
        history_section += (
            "| Confidence | Predicted | Actual | Bets | Calibration |\n"
        )
        history_section += (
            "|------------|-----------|--------|------|-------------|\n"
        )

        for bucket in calibration["buckets"]:
            if bucket["num_bets"] > 0:
                status_map = {
                    "well_calibrated": "✅ Well calibrated",
                    "acceptable": "⚠️ Acceptable",
                    "overconfident": "🔴 Overconfident",
                    "underconfident": "🔵 Underconfident",
                }

                history_section += (
                    f"| {bucket['range']} | "
                    f"{bucket['predicted_win_rate']:.1%} | "
                    f"{bucket['actual_win_rate']:.1%} | "
                    f"{bucket['num_bets']} | "
                    f"{status_map.get(bucket['status'], 'Unknown')} |\n"
                )

        # Edge Validation
        edge_val = analytics_advanced.calculate_edge_validation(
            closed_bets, min_bets=10
        )

        history_section += "\n### Edge Validation\n\n"
        history_section += (
            "Compares predicted market edge vs actual realized edge:\n\n"
        )
        history_section += "| Edge Range | Predicted | Realized | Accuracy |\n"
        history_section += "|------------|-----------|----------|----------|\n"

        for bucket in edge_val["buckets"]:
            if bucket["status"] == "sufficient_data":
                history_section += (
                    f"| {bucket['range']} | "
                    f"{bucket['avg_predicted_edge']:+.1%} | "
                    f"{bucket['avg_realized_edge']:+.1%} | "
                    f"{bucket['accuracy']:.0%} |\n"
                )

        # Model Trends
        trends = analytics_advanced.calculate_model_trends(closed_bets)

        history_section += "\n### Performance Evolution\n\n"
        history_section += "30-day rolling window analysis:\n\n"
        history_section += "| Period | Win Rate | Confidence | Calibration |\n"
        history_section += "|--------|----------|------------|-------------|\n"

        for period in trends["periods"][-4:]:  # Last 4 weeks
            history_section += (
                f"| {period['period_label']} | "
                f"{period['win_rate']:.1%} | "
                f"{period['avg_confidence']:.0%} | "
                f"{period['calibration_score']:.0%} |\n"
            )

        history_section += "\n#### Recent Closed Bets (Last 20)\n\n"

        recent_closed = sorted(
            closed_bets, key=lambda x: x["timestamp_closed"], reverse=True
        )[:20]

        for bet in recent_closed:
            timestamp = to_cet(bet["timestamp_closed"])
            time_str = (
                timestamp.strftime("%Y-%m-%d") if timestamp else "Unknown"
            )

            was_correct = bet["action"] == bet["actual_outcome"]
            result_icon = "✅" if was_correct else "❌"

            ai_prob = (
                bet["ai_probability"]
                if bet["ai_probability"] is not None
                else 0.0
            )
            conf = (
                bet["confidence_score"]
                if bet["confidence_score"] is not None
                else 0.0
            )
            reasoning = (
                bet["ai_reasoning"]
                if bet["ai_reasoning"] is not None
                else "N/A"
            )

            history_section += f"""**{time_str} - {bet['question'][:50]}...**
{result_icon} Predicted: {bet['action']} ({ai_prob:.0%}) | Actual: {bet['actual_outcome']} | Confidence: {conf:.0%} | P/L: ${bet['profit_loss']:+.2f}
Reasoning: {reasoning[:120]}...

"""

    # === ASSEMBLY ===
    content = header + active_section + rejected_section + history_section
    content += "\n---\n*Generated by Polymarket AI Bot v2.0*\n"

    with open("AI_DECISIONS.md", "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ AI_DECISIONS.md generated successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_ai_decisions_file()
