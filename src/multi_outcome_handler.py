import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.db_models import ActiveBet
from src.prompts.multi_outcome_prompt import generate_multi_outcome_prompt


class MultiOutcomeHandler:
    def __init__(self, db_session_factory, config: Dict[str, Any]):
        self.Session = db_session_factory
        self.config = config
        self.logger = logging.getLogger(__name__)

    def group_markets(self, markets: List[Any]) -> Dict[str, Any]:  # noqa: C901
        """
        Groups markets by parent event using heuristic strategies.

        Returns:
        {
            'single_markets': [market1, ...],
            'multi_outcome_events': {
                'parent_slug': [marketA, marketB, ...],
                ...
            }
        }
        """
        singles = []

        # Helper to get raw data if market is pydantic model or dict
        def get_field(m, field):
            if hasattr(m, field):
                return getattr(m, field)
            return m.get(field)

        potential_groups = defaultdict(list)

        for market in markets:
            question = get_field(market, "question")

            # Heuristic 1: "X price on Y: Range" or "X price on Y - Range"
            # Pattern: (Main Event) [:|-] (Variant)
            match = re.match(r"^(.*?)(?::| -| –) .+$", question)
            if match:
                parent_key = match.group(1).strip()
                potential_groups[parent_key].append(market)
                continue

            potential_groups[question].append(market)

        # Merge groups based on similarity
        merged_groups = defaultdict(list)
        keys = sorted(list(potential_groups.keys()))

        # Simple clustering: if distinct keys share a long common prefix (e.g. >20 chars), merge.
        skip_keys = set()
        for i in range(len(keys)):
            k1 = keys[i]
            if k1 in skip_keys:
                continue

            merged_groups[k1].extend(potential_groups[k1])

            for j in range(i + 1, len(keys)):
                k2 = keys[j]
                if k2 in skip_keys:
                    continue

                # Check similarity: Common prefix
                prefix_len = 0
                min_len = min(len(k1), len(k2))
                while prefix_len < min_len and k1[prefix_len] == k2[prefix_len]:
                    prefix_len += 1

                if prefix_len > 15:  # Threshold: "Will Trump deport" is ~17 chars
                    # Merge k2 into k1
                    merged_groups[k1].extend(potential_groups[k2])
                    skip_keys.add(k2)

        # Now use merged_groups as potential_groups
        potential_groups = merged_groups

        # Post-process groups
        final_groups = {}

        for key, group_markets in potential_groups.items():
            if len(group_markets) >= self.config["detection"]["min_outcomes_threshold"]:
                # likely multi-outcome
                slug = key.lower().replace(" ", "-").replace("?", "").replace(":", "")
                # Ensure unique
                final_groups[slug] = group_markets
            else:
                # Add back to singles
                for m in group_markets:
                    singles.append(m)

        return {"single_markets": singles, "multi_outcome_events": final_groups}

    def analyze_multi_outcome_event(
        self, parent_slug: str, outcomes: List[Any], gemini_client
    ) -> Optional[Dict]:
        """
        Coordinates analysis of a multi-outcome event.
        """
        self.logger.info(
            f"Analyzing multi-outcome event: {parent_slug} ({len(outcomes)} outcomes)"
        )

        # Prepare data for prompt
        event_data = {"parent_slug": parent_slug, "outcomes": outcomes}

        prompt = generate_multi_outcome_prompt(event_data)

        try:
            from google.genai import types

            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )

            import json

            text_response = response.text
            # Clean markdown
            if "```json" in text_response:
                text_response = text_response.split("```json")[1].split("```")[0]
            elif "```" in text_response:
                text_response = text_response.split("```")[1].split("```")[0]

            analysis = json.loads(text_response.strip())

            # Validate distribution
            if not self.validate_distribution(analysis.get("distribution", {})):
                self.logger.warning(f"Distribution validation failed for {parent_slug}")
                # We could force normalize here if config says so
                if self.config["analysis"]["normalize_distribution"]:
                    analysis["distribution"] = self._force_normalize(
                        analysis["distribution"]
                    )
                else:
                    return None

            return analysis

        except Exception as e:
            self.logger.error(f"Error analyzing multi-outcome {parent_slug}: {e}")
            return None

    def validate_distribution(self, distribution: Dict[str, float]) -> bool:
        """Checks if probability sum is ~1.0"""
        total = sum(distribution.values())
        valid = 0.98 <= total <= 1.02
        if not valid:
            self.logger.warning(f"Distribution sum invalid: {total}")
        return valid

    def _force_normalize(self, distribution: Dict[str, float]) -> Dict[str, float]:
        total = sum(distribution.values())
        if total == 0:
            return distribution
        return {k: v / total for k, v in distribution.items()}

    def check_existing_bets(self, parent_event_slug: str) -> Optional[str]:
        """Checks if bets exist for this parent event."""
        if not self.config["conflicts"]["block_on_existing_bet"]:
            return None

        session = self.Session()
        try:
            exists = (
                session.query(ActiveBet)
                .filter(ActiveBet.parent_event_slug == parent_event_slug)
                .first()
            )

            if exists:
                return f"Bet already active on event {parent_event_slug}"
            return None
        finally:
            session.close()

    def select_best_outcome(
        self, analysis: Dict, market_map: Dict[str, Any]
    ) -> Optional[Dict]:
        """
        Selects the best outcome based on strategy.
        market_map: {outcome_variant_id (or slug): MarketData}
        """
        best_outcome = None
        max_abs_edge = 0.0

        strategy = self.config["strategy"]
        min_edge = strategy["min_edge_absolute"]
        min_conf = strategy["min_confidence"]

        distribution = analysis.get("distribution", {})
        best_pick_ai = analysis.get("best_pick", {})

        # We can iterate through distribution and find the matching market
        for outcome_id, ai_prob in distribution.items():
            market = market_map.get(outcome_id)
            if not market:
                continue

            # Retrieve market price
            # Assuming market has 'yes_price'
            market_price = getattr(market, "yes_price", 0.5)

            edge = ai_prob - market_price

            if abs(edge) >= min_edge:
                # Check if this is the "best" so far
                if abs(edge) > max_abs_edge:
                    max_abs_edge = abs(edge)
                    best_outcome = {
                        "market": market,
                        "ai_probability": ai_prob,
                        "edge": edge,
                        "confidence": best_pick_ai.get("confidence", 0.7),  # Fallback
                        "action": "YES" if edge > 0 else "NO",
                        "reasoning": analysis.get("reasoning", ""),
                    }

        if best_outcome and best_outcome["confidence"] >= min_conf:
            return best_outcome

        return None

    def persist_analysis(
        self, parent_slug: str, analysis: Dict, market_map: Dict[str, Any]
    ) -> int:
        """
        Persists complete multi-outcome analysis to database.

        Args:
            parent_slug: Parent event identifier
            analysis: Complete AI analysis with distribution
            market_map: Mapping of outcome slugs to MarketData

        Returns:
            analysis_id: Database ID of stored analysis
        """
        from src import database

        distribution = analysis.get("distribution", {})
        market_prices = {}

        for slug, market in market_map.items():
            if hasattr(market, "yes_price"):
                market_prices[slug] = market.yes_price
            else:
                market_prices[slug] = market.get("yes_price", 0.5)

        best_pick = analysis.get("best_pick", {})
        best_outcome_slug = best_pick.get("market_slug")
        reasoning = analysis.get("reasoning", "")

        analysis_id = database.insert_multi_outcome_analysis(
            parent_event_slug=parent_slug,
            full_distribution=distribution,
            market_prices=market_prices,
            reasoning=reasoning,
            best_outcome_slug=best_outcome_slug,
        )

        return analysis_id

    def select_multiple_outcomes(
        self, analysis: Dict, market_map: Dict[str, Any], max_bets: int = None
    ) -> List[Dict]:
        """
        Selects MULTIPLE profitable outcomes from a multi-outcome event.

        Args:
            analysis: AI analysis with distribution
            market_map: Mapping of slugs to MarketData
            max_bets: Maximum number of bets to return (default from config)

        Returns:
            List of outcome dicts with market, ai_probability, edge, etc.
        """
        if not self.config["strategy"].get("bet_alternatives_enabled", True):
            max_bets = 1  # Nur beste Option
        elif max_bets is None:
            max_bets = self.config["strategy"].get("max_multi_outcome_bets", 2)

        strategy = self.config["strategy"]
        min_edge = strategy["min_edge_absolute"]
        min_conf = strategy["min_confidence"]

        distribution = analysis.get("distribution", {})
        best_pick = analysis.get("best_pick", {})
        base_confidence = best_pick.get("confidence", 0.7)

        candidates = []

        for outcome_slug, ai_prob in distribution.items():
            market = market_map.get(outcome_slug)
            if not market:
                continue

            if hasattr(market, "yes_price"):
                market_price = market.yes_price
            else:
                market_price = market.get("yes_price", 0.5)

            edge = ai_prob - market_price

            # Check if this outcome was selected for betting
            is_best = outcome_slug == best_pick.get("market_slug")

            min_edge_for_alt = self.config["strategy"].get(
                "alternatives_min_edge", min_edge
            )
            required_edge = min_edge if is_best else min_edge_for_alt

            # Only consider outcomes with sufficient edge
            if abs(edge) >= required_edge:
                # Reduce confidence slightly for non-best picks
                confidence = base_confidence if is_best else (base_confidence * 0.9)

                if confidence >= min_conf:
                    candidates.append(
                        {
                            "market": market,
                            "outcome_slug": outcome_slug,
                            "ai_probability": ai_prob,
                            "edge": edge,
                            "confidence": confidence,
                            "action": "YES" if edge > 0 else "NO",
                            "is_best_pick": is_best,
                        }
                    )

        # Sort by absolute edge (highest first)
        candidates.sort(key=lambda x: abs(x["edge"]), reverse=True)

        # Return top N
        selected = candidates[:max_bets]

        self.logger.info(
            f"📊 Selected {len(selected)}/{len(candidates)} profitable outcomes "
            f"from {len(distribution)} total options"
        )

        return selected
