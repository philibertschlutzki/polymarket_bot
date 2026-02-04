import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from src.db_models import ActiveBet
from src.prompts.multi_outcome_prompt import generate_multi_outcome_prompt

class MultiOutcomeHandler:
    def __init__(self, db_session_factory, config: Dict[str, Any]):
        self.Session = db_session_factory
        self.config = config
        self.logger = logging.getLogger(__name__)

    def group_markets(self, markets: List[Any]) -> Dict[str, Any]:
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
        grouped = defaultdict(list)
        singles = []

        # Helper to get raw data if market is pydantic model or dict
        def get_field(m, field):
            if hasattr(m, field):
                return getattr(m, field)
            return m.get(field)

        # 1. Group by Title Similarity (Method C - most robust fallback)
        # We look for common prefixes. This is O(N^2) naive, but with 100 markets it's fine.
        # Better: Clustering.
        # Simple approach: Tokenize title, find overlapping clusters.

        # Simplified approach for this task:
        # Use a "Group Key" derived from title.
        # e.g. "Bitcoin price on Feb 4: <80k" -> "Bitcoin price on Feb 4"
        # Regex for common patterns: ":", "-", "Will X be..."

        processed_slugs = set()

        # First pass: Identify obvious groups via API metadata if available (not implemented in standard MarketData yet)
        # Assuming we only have standard fields for now.

        # We will iterate and build groups dynamically.
        # Key: Normalized Title Prefix

        potential_groups = defaultdict(list)

        for market in markets:
            question = get_field(market, 'question')
            market_slug = get_field(market, 'market_slug')

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
            if k1 in skip_keys: continue

            merged_groups[k1].extend(potential_groups[k1])

            for j in range(i+1, len(keys)):
                k2 = keys[j]
                if k2 in skip_keys: continue

                # Check similarity: Common prefix
                prefix_len = 0
                min_len = min(len(k1), len(k2))
                while prefix_len < min_len and k1[prefix_len] == k2[prefix_len]:
                    prefix_len += 1

                if prefix_len > 15: # Threshold: "Will Trump deport" is ~17 chars
                    # Merge k2 into k1
                    merged_groups[k1].extend(potential_groups[k2])
                    skip_keys.add(k2)

        # Now use merged_groups as potential_groups
        potential_groups = merged_groups

        # Post-process groups
        # If a group has only 1 item, it's likely a single market (unless explicit multi-outcome detected later)
        # If > 1, check if they truly belong together.

        # We need a robust slug for the parent event.
        # If we derived a key "Bitcoin price on Feb 4", we make a slug from it.

        final_groups = {}

        for key, group_markets in potential_groups.items():
            if len(group_markets) >= self.config['detection']['min_outcomes_threshold']:
                # likely multi-outcome
                slug = key.lower().replace(" ", "-").replace("?", "").replace(":", "")
                # Ensure unique
                final_groups[slug] = group_markets
            else:
                # Add back to singles
                for m in group_markets:
                    singles.append(m)

        return {
            'single_markets': singles,
            'multi_outcome_events': final_groups
        }

    def analyze_multi_outcome_event(
        self,
        parent_slug: str,
        outcomes: List[Any],
        gemini_client
    ) -> Optional[Dict]:
        """
        Coordinates analysis of a multi-outcome event.
        """
        self.logger.info(f"Analyzing multi-outcome event: {parent_slug} ({len(outcomes)} outcomes)")

        # Prepare data for prompt
        event_data = {
            'parent_slug': parent_slug,
            'outcomes': outcomes
        }

        prompt = generate_multi_outcome_prompt(event_data)

        try:
            # Call Gemini (we assume gemini_client has a method compatible with this)
            # The main.py uses _generate_gemini_response which expects client and prompt.
            # We might need to call that helper or use the client directly.
            # Assuming gemini_client is the raw genai.Client

            # We need the response parsing logic from main.py or replicate it.
            # To avoid circular imports or duplication, we should probably pass a callback or
            # expect `gemini_client` to be a wrapper.
            # But the plan said `gemini_client`.

            # Let's assume we use the same `_execute_gemini_request` logic.
            # Since that function is in main.py, we can't easily import it without circular dep if main imports this.
            # We will rely on the caller (main.py) to pass a callable `analyze_fn` or similar,
            # OR we implement the call here using google.genai directly.

            from google.genai import types

            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
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
            if not self.validate_distribution(analysis.get('distribution', {})):
                self.logger.warning(f"Distribution validation failed for {parent_slug}")
                # We could force normalize here if config says so
                if self.config['analysis']['normalize_distribution']:
                    analysis['distribution'] = self._force_normalize(analysis['distribution'])
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
        if not self.config['conflicts']['block_on_existing_bet']:
            return None

        session = self.Session()
        try:
            exists = session.query(ActiveBet).filter(
                ActiveBet.parent_event_slug == parent_event_slug
            ).first()

            if exists:
                return f"Bet already active on event {parent_event_slug}"
            return None
        finally:
            session.close()

    def select_best_outcome(self, analysis: Dict, market_map: Dict[str, Any]) -> Optional[Dict]:
        """
        Selects the best outcome based on strategy.
        market_map: {outcome_variant_id (or slug): MarketData}
        """
        best_outcome = None
        max_abs_edge = 0.0

        strategy = self.config['strategy']
        min_edge = strategy['min_edge_absolute']
        min_conf = strategy['min_confidence']

        distribution = analysis.get('distribution', {})
        best_pick_ai = analysis.get('best_pick', {})

        # We can iterate through distribution and find the matching market
        for outcome_id, ai_prob in distribution.items():
            market = market_map.get(outcome_id)
            if not market:
                continue

            # Retrieve market price
            # Assuming market has 'yes_price'
            market_price = getattr(market, 'yes_price', 0.5)

            edge = ai_prob - market_price

            # Logic: If edge is positive and > threshold
            # Also check confidence from AI analysis (global or per outcome?)
            # Usually analysis has a global reasoning or specific confidence.
            # Let's use the 'best_pick' from AI as a guide, but verify with our calc.

            if abs(edge) >= min_edge:
                # Check if this is the "best" so far
                if abs(edge) > max_abs_edge:
                    max_abs_edge = abs(edge)
                    best_outcome = {
                        'market': market,
                        'ai_probability': ai_prob,
                        'edge': edge,
                        'confidence': best_pick_ai.get('confidence', 0.7), # Fallback
                        'action': 'YES' if edge > 0 else 'NO',
                        'reasoning': analysis.get('reasoning', '')
                    }

        if best_outcome and best_outcome['confidence'] >= min_conf:
            return best_outcome

        return None
