from unittest.mock import MagicMock, patch

import pytest

from src.db_models import ActiveBet
from src.multi_outcome_handler import MultiOutcomeHandler


@patch("src.multi_outcome_handler.generate_multi_outcome_prompt")
def test_analyze_flow(mock_prompt, caplog):
    mock_prompt.return_value = "Prompt"

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '```json\n{"distribution": {"s1": 0.5, "s2": 0.5}, "sum_probabilities": 1.0, "best_pick": {"market_slug": "s1", "confidence": 0.8}}\n```'
    mock_client.models.generate_content.return_value = mock_response

    handler = MultiOutcomeHandler(
        MagicMock(), {"analysis": {"normalize_distribution": True}, "logging": {}}
    )

    outcomes = [{"market_slug": "s1"}, {"market_slug": "s2"}]
    analysis = handler.analyze_multi_outcome_event("parent", outcomes, mock_client)

    assert analysis is not None
    assert analysis["distribution"]["s1"] == 0.5


@patch("src.multi_outcome_handler.ActiveBet")
def test_check_conflict(mock_active_bet):
    # Mock session
    mock_session = MagicMock()
    mock_query = mock_session.query.return_value
    mock_filter = mock_query.filter.return_value

    # Simulate existing bet
    mock_filter.first.return_value = ActiveBet(bet_id=1)

    mock_factory = MagicMock(return_value=mock_session)

    handler = MultiOutcomeHandler(
        mock_factory, {"conflicts": {"block_on_existing_bet": True}}
    )

    msg = handler.check_existing_bets("parent")
    assert msg is not None
    assert "already active" in msg

    # Simulate no bet
    mock_filter.first.return_value = None
    msg = handler.check_existing_bets("parent")
    assert msg is None
