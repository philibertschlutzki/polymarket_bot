"""
Unit tests for resolution_checker module
"""

import pytest
import requests
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src import resolution_checker


def test_determine_outcome_yes_win():
    """Test: YES wins with price 1.0"""
    market = {
        "id": "test-market-yes",
        "closed": True,
        "resolvedBy": "0xResolver",
        "outcomes": [{"id": "YES", "price": "1.0"}]
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.60,
        "action": "YES"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome == "YES"
    assert pl > 0, "Expected profit for winning YES bet"


def test_determine_outcome_no_win():
    """Test: NO wins with price 0.0"""
    market = {
        "id": "test-market-no",
        "closed": True,
        "resolvedBy": "0xResolver",
        "outcomes": [{"id": "YES", "price": "0.0"}]
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.40,
        "action": "NO"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome == "NO"
    assert pl > 0, "Expected profit for winning NO bet"


def test_determine_outcome_loss():
    """Test: Loss scenario"""
    market = {
        "id": "test-market-loss",
        "closed": True,
        "resolvedBy": "0xResolver",
        "outcomes": [{"id": "YES", "price": "0.0"}]
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.60,
        "action": "YES"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome == "NO"
    assert pl < 0, "Expected loss for losing bet"


def test_determine_outcome_disputed():
    """Test: Disputed outcome with price in 0.1-0.9 range"""
    market = {
        "id": "test-market-disputed",
        "closed": True,
        "resolvedBy": "0xResolver",
        "outcomes": [{"id": "YES", "price": "0.45"}]
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.60,
        "action": "YES"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome == "DISPUTED"
    assert pl == 0.0, "Disputed bets should have zero P/L initially"


def test_determine_outcome_not_resolved():
    """Test: Market not yet resolved"""
    market = {
        "id": "test-market-open",
        "closed": False,
        "resolvedBy": None,
        "outcomes": [{"id": "YES", "price": "0.60"}]
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.60,
        "action": "YES"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome is None
    assert pl == 0.0


def test_determine_outcome_no_outcomes():
    """Test: Market with no outcomes data"""
    market = {
        "id": "test-market-empty",
        "closed": True,
        "resolvedBy": "0xResolver",
        "outcomes": []
    }
    bet = {
        "stake_usdc": 100.0,
        "entry_price": 0.60,
        "action": "YES"
    }
    outcome, pl = resolution_checker._determine_outcome(market, bet)
    assert outcome is None


@patch('src.resolution_checker.requests.post')
def test_query_goldsky_success(mock_post):
    """Test successful Goldsky API query"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "markets": [
                {
                    "id": "test-market-1",
                    "closed": True,
                    "resolvedBy": "0xResolver",
                    "outcomes": [{"price": "1.0"}]
                }
            ]
        }
    }
    mock_post.return_value = mock_response

    result = resolution_checker._query_goldsky(["test-market-1"])

    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "test-market-1"
    assert result[0]["closed"] is True


@patch('src.resolution_checker.requests.post')
def test_query_goldsky_error(mock_post):
    """Test Goldsky API error handling"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "errors": [{"message": "Test error"}]
    }
    mock_post.return_value = mock_response

    result = resolution_checker._query_goldsky(["test-market"])

    assert result is None


@patch('src.resolution_checker.requests.post')
def test_query_goldsky_network_error(mock_post):
    """Test network error with retries"""
    mock_post.side_effect = requests.exceptions.RequestException("Network error")

    result = resolution_checker._query_goldsky(["test-market"])

    assert result is None
    assert mock_post.call_count == resolution_checker.MAX_RETRIES


def test_parse_datetime_string():
    """Test datetime parsing from string"""
    dt_str = "2026-02-04T10:00:00Z"
    result = resolution_checker._parse_datetime(dt_str)

    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_parse_datetime_object():
    """Test datetime parsing from datetime object"""
    dt_obj = datetime(2026, 2, 4, 10, 0, 0)
    result = resolution_checker._parse_datetime(dt_obj)

    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_parse_datetime_aware():
    """Test datetime parsing with timezone-aware object"""
    dt_aware = datetime(2026, 2, 4, 10, 0, 0, tzinfo=timezone.utc)
    result = resolution_checker._parse_datetime(dt_aware)

    assert result == dt_aware
