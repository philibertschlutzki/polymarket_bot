import pytest
from unittest.mock import MagicMock, Mock
from src.multi_outcome_handler import MultiOutcomeHandler

class TestMultiOutcomeHandler:
    @pytest.fixture
    def handler(self):
        config = {
            'detection': {'min_outcomes_threshold': 3},
            'analysis': {'normalize_distribution': True},
            'strategy': {'min_edge_absolute': 0.10, 'min_confidence': 0.70},
            'conflicts': {'block_on_existing_bet': True}
        }
        return MultiOutcomeHandler(MagicMock(), config)

    def test_group_markets(self, handler):
        markets = [
            {'market_slug': 's1', 'question': 'Bitcoin price on Feb 4: <80k'},
            {'market_slug': 's2', 'question': 'Bitcoin price on Feb 4: 80k-90k'},
            {'market_slug': 's3', 'question': 'Bitcoin price on Feb 4: >90k'},
            {'market_slug': 's4', 'question': 'Other event'},
        ]

        groups = handler.group_markets(markets)

        assert len(groups['single_markets']) == 1
        assert groups['single_markets'][0]['market_slug'] == 's4'
        assert len(groups['multi_outcome_events']) == 1

        slug = list(groups['multi_outcome_events'].keys())[0]
        assert 'bitcoin-price-on-feb-4' in slug
        assert len(groups['multi_outcome_events'][slug]) == 3

    def test_validate_distribution(self, handler):
        assert handler.validate_distribution({'a': 0.5, 'b': 0.5}) is True
        assert handler.validate_distribution({'a': 0.5, 'b': 0.6}) is False # 1.1

    def test_select_best_outcome(self, handler):
        analysis = {
            'distribution': {'s1': 0.4, 's2': 0.3, 's3': 0.3},
            'best_pick': {'confidence': 0.8}
        }
        # s1: 0.4 vs 0.5 (Edge -0.1)
        # s2: 0.3 vs 0.1 (Edge +0.2)
        # s3: 0.3 vs 0.3 (Edge 0)

        market_map = {
            's1': MagicMock(yes_price=0.5, market_slug='s1'),
            's2': MagicMock(yes_price=0.1, market_slug='s2'),
            's3': MagicMock(yes_price=0.3, market_slug='s3'),
        }

        best = handler.select_best_outcome(analysis, market_map)

        assert best is not None
        assert best['market'].market_slug == 's2'
        assert best['edge'] == pytest.approx(0.2)
        assert best['action'] == 'YES'

    def test_select_best_outcome_no_edge(self, handler):
        analysis = {
            'distribution': {'s1': 0.5},
            'best_pick': {'confidence': 0.8}
        }
        market_map = {
            's1': MagicMock(yes_price=0.5, market_slug='s1')
        }
        # Edge 0 < 0.10
        best = handler.select_best_outcome(analysis, market_map)
        assert best is None
