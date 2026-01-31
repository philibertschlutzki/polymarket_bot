import logging
from datetime import datetime, timedelta
import database
from dashboard import to_cet, CET_TZ

logger = logging.getLogger(__name__)

def generate_ai_decisions_file():
    """Generates AI_DECISIONS.md with all AI analysis details."""

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
        ai_prob = bet['ai_probability'] if bet['ai_probability'] is not None else 0.0
        conf = bet['confidence_score'] if bet['confidence_score'] is not None else 0.0
        edge = bet['edge'] if bet['edge'] is not None else 0.0
        reasoning = bet['ai_reasoning'] if bet['ai_reasoning'] is not None else 'No reasoning available'

        # End Date
        end_date_str = "Unknown"
        if bet['end_date']:
            try:
                ed_cet = to_cet(bet['end_date'])
                if ed_cet:
                    end_date_str = ed_cet.strftime('%Y-%m-%d %H:%M %Z')
            except:
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
    rejected_section += f"*Showing last {len(rejected_markets)} rejected analyses*\n\n"

    # Group by rejection reason
    rejection_groups = {}
    for rej in rejected_markets:
        reason = rej['rejection_reason']
        if reason not in rejection_groups:
            rejection_groups[reason] = []
        rejection_groups[reason].append(rej)

    for reason, markets in rejection_groups.items():
        rejected_section += f"### {reason.replace('_', ' ').title()} ({len(markets)})\n\n"

        for market in markets[:10]:  # Max 10 per category
            ai_prob = market['ai_probability'] if market['ai_probability'] is not None else 0.0
            edge = market['edge'] if market['edge'] is not None else 0.0
            reasoning = market['ai_reasoning'] if market['ai_reasoning'] is not None else 'N/A'
            conf = market['confidence_score'] if market['confidence_score'] is not None else 0.0

            timestamp = to_cet(market['timestamp_analyzed'])
            time_str = timestamp.strftime('%Y-%m-%d %H:%M') if timestamp else "Unknown"

            rejected_section += f"""**{market['question'][:60]}...**
*Analyzed: {time_str}*
Market: {market['market_price']:.2f} | AI: {ai_prob:.2f} | Edge: {edge:+.1%} | Conf: {conf:.0%}
Reasoning: {reasoning[:150]}...

"""

        rejected_section += "\n"

    # === HISTORICAL ANALYSIS ===
    history_section = "## 📊 Historical Analysis\n\n"
    history_section += "### Post-Mortem: AI Predictions vs Actual Outcomes\n\n"

    if not closed_bets:
        history_section += "*No closed bets yet for analysis.*\n\n"
    else:
        # Calculate accuracy by confidence level
        conf_buckets = {
            'High (>80%)': [],
            'Medium (60-80%)': [],
            'Low (<60%)': []
        }

        for bet in closed_bets:
            conf = bet['confidence_score'] if bet['confidence_score'] is not None else 0.0
            was_correct = (bet['action'] == bet['actual_outcome'])

            if conf >= 0.80:
                conf_buckets['High (>80%)'].append(was_correct)
            elif conf >= 0.60:
                conf_buckets['Medium (60-80%)'].append(was_correct)
            else:
                conf_buckets['Low (<60%)'].append(was_correct)

        history_section += "#### Accuracy by Confidence Level\n\n"
        history_section += "| Confidence | Bets | Accuracy | Notes |\n"
        history_section += "|------------|------|----------|-------|\n"

        for level, results in conf_buckets.items():
            if results:
                accuracy = sum(results) / len(results) * 100
                history_section += f"| {level} | {len(results)} | {accuracy:.1f}% | {'✅ Good calibration' if accuracy >= 70 else '⚠️ Needs improvement'} |\n"
            else:
                history_section += f"| {level} | 0 | N/A | - |\n"

        history_section += "\n#### Recent Closed Bets (Last 20)\n\n"

        recent_closed = sorted(closed_bets, key=lambda x: x['timestamp_closed'], reverse=True)[:20]

        for bet in recent_closed:
            timestamp = to_cet(bet['timestamp_closed'])
            time_str = timestamp.strftime('%Y-%m-%d') if timestamp else "Unknown"

            was_correct = (bet['action'] == bet['actual_outcome'])
            result_icon = "✅" if was_correct else "❌"

            ai_prob = bet['ai_probability'] if bet['ai_probability'] is not None else 0.0
            conf = bet['confidence_score'] if bet['confidence_score'] is not None else 0.0
            reasoning = bet['ai_reasoning'] if bet['ai_reasoning'] is not None else 'N/A'

            history_section += f"""**{time_str} - {bet['question'][:50]}...**
{result_icon} Predicted: {bet['action']} ({ai_prob:.0%}) | Actual: {bet['actual_outcome']} | Confidence: {conf:.0%} | P/L: ${bet['profit_loss']:+.2f}
AI Reasoning: {reasoning[:120]}...

"""

    # === ASSEMBLY ===
    content = header + active_section + rejected_section + history_section
    content += "\n---\n*Generated by Polymarket AI Bot v2.0*\n"

    with open('AI_DECISIONS.md', 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info("✅ AI_DECISIONS.md generated successfully")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_ai_decisions_file()
