from typing import Any, Dict


def generate_multi_outcome_prompt(event_data: Dict[str, Any]) -> str:
    """
    Generates a prompt for multi-outcome event analysis.
    event_data: {
        'parent_slug': str,
        'outcomes': List[MarketData] or List[Dict]
    }
    """
    parent_slug = event_data.get("parent_slug", "Unknown Event")
    outcomes = event_data.get("outcomes", [])

    # Format outcomes table
    outcomes_text = "MARKET ID | OUTCOME / RANGE | CURRENT PRICE (YES)\n"
    outcomes_text += "--- | --- | ---\n"

    for outcome in outcomes:
        # Handle both MarketData object and Dict
        if hasattr(outcome, "question"):
            question = outcome.question
            market_slug = outcome.market_slug
            price = outcome.yes_price
        else:
            question = outcome.get("question", "")
            market_slug = outcome.get("market_slug", "")
            price = outcome.get("yes_price", 0.5)

        outcomes_text += f"{market_slug} | {question} | {price:.3f}\n"

    num_outcomes = len(outcomes)

    prompt = f"""
You are an expert prediction market analyst. You are analyzing a "Mutually Exclusive" multi-outcome event on Polymarket.
This means ONLY ONE of the outcomes listed below can resolve to YES. All others will resolve to NO.
Therefore, the sum of the true probabilities of all outcomes must equal exactly 100% (1.0).

EVENT ID: {parent_slug}
NUMBER OF OUTCOMES: {num_outcomes}

AVAILABLE OUTCOMES AND PRICES:
{outcomes_text}

TASK:
1. Analyze the event and all outcomes collectively.
2. Estimate the probability for EACH outcome.
3. ENSURE the sum of your estimated probabilities is EXACTLY 1.0 (normalize if necessary).
4. Compare your probabilities with the market prices.
5. Identify the "Best Pick" (highest positive edge = Your Prob - Market Price).

OUTPUT FORMAT (JSON ONLY):
{{
  "distribution": {{
    "market_slug_of_outcome_1": 0.15,
    "market_slug_of_outcome_2": 0.25,
    ... (include ALL outcomes)
  }},
  "sum_probabilities": 1.0,
  "reasoning": "Detailed reasoning for the distribution...",
  "best_pick": {{
    "market_slug": "...",
    "direction": "YES",
    "confidence": 0.75,
    "reasoning": "Why this is the best bet..."
  }}
}}

NOTES:
- Use current news and data (via Google Search if available to you) to inform your probabilities.
- Be precise.
"""
    return prompt
