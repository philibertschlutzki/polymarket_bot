import yaml
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

CONFIG_PATH = "config/multi_outcome.yaml"


def get_default_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "detection": {
            "use_url_pattern": True,
            "use_api_metadata": True,
            "use_title_matching": True,
            "min_outcomes_threshold": 3,
        },
        "analysis": {
            "use_specialized_prompt": True,
            "normalize_distribution": True,
            "force_normalization_threshold": 0.02,
            "min_probability_threshold": 0.01,
            "require_all_outcomes": True,
            "max_outcomes_per_event": 50,
        },
        "strategy": {
            "min_edge_absolute": 0.10,
            "min_confidence": 0.70,
            "select_best_only": True,
        },
        "conflicts": {"block_on_existing_bet": True, "allow_hedging": False},
        "logging": {
            "log_full_distribution": True,
            "log_rejected_outcomes": True,
            "log_normalization_warnings": True,
        },
    }


def load_multi_outcome_config() -> Dict[str, Any]:
    """Loads the multi-outcome configuration from YAML."""
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"Config file not found at {CONFIG_PATH}, using defaults.")
        return get_default_config()

    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
            if not config or "multi_outcome" not in config:
                return get_default_config()
            return config.get("multi_outcome", get_default_config())
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return get_default_config()
