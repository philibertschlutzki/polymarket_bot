#!/usr/bin/env python3
"""
Test suite for Polymarket AI Value Bet Bot
Tests the core functionality with mock data
"""

import unittest
from unittest.mock import Mock, patch
from pydantic import ValidationError
from main import (
    MarketData, 
    AIAnalysis, 
    TradingRecommendation,
    calculate_kelly_stake,
    test_clob_connection,
    fetch_active_markets
)


class TestMarketDataModels(unittest.TestCase):
    """Test data models"""
    
    def test_market_data_creation(self):
        """Test MarketData model creation"""
        market = MarketData(
            question="Will Bitcoin reach $100k in 2024?",
            description="Test market",
            market_slug="test-123",
            yes_price=0.65,
            volume=50000.0,
            end_date="2024-12-31"
        )
        self.assertEqual(market.yes_price, 0.65)
        self.assertEqual(market.volume, 50000.0)
    
    def test_ai_analysis_validation(self):
        """Test AIAnalysis model validates probabilities"""
        # Valid analysis
        analysis = AIAnalysis(
            estimated_probability=0.75,
            confidence_score=0.8,
            reasoning="Based on current trends..."
        )
        self.assertEqual(analysis.estimated_probability, 0.75)
        
        # Invalid probability should be caught by Pydantic
        with self.assertRaises(ValidationError):
            AIAnalysis(
                estimated_probability=1.5,  # Invalid: > 1.0
                confidence_score=0.8,
                reasoning="Test"
            )


class TestKellyCriterion(unittest.TestCase):
    """Test Kelly Criterion calculations"""
    
    def test_kelly_with_positive_edge(self):
        """Test Kelly calculation with positive edge"""
        recommendation = calculate_kelly_stake(
            ai_probability=0.7,
            market_price=0.5,
            confidence=0.9,
            capital=1000.0
        )
        
        self.assertEqual(recommendation.action, "YES")
        self.assertGreater(recommendation.stake_usdc, 0)
        self.assertLessEqual(recommendation.stake_usdc, 500)  # Max 50% of capital
        self.assertGreater(recommendation.expected_value, 0)
    
    def test_kelly_with_negative_edge(self):
        """Test Kelly calculation with negative edge (should recommend NO or PASS)"""
        recommendation = calculate_kelly_stake(
            ai_probability=0.3,
            market_price=0.5,
            confidence=0.9,
            capital=1000.0
        )
        
        # When AI probability is much lower than market price, should be NO or PASS
        self.assertIn(recommendation.action, ["NO", "PASS"])
        # If action is PASS, stake should be 0
        if recommendation.action == "PASS":
            self.assertEqual(recommendation.stake_usdc, 0.0)
    
    def test_kelly_caps_at_50_percent(self):
        """Test Kelly is capped at 50% of capital"""
        recommendation = calculate_kelly_stake(
            ai_probability=0.99,
            market_price=0.1,
            confidence=1.0,
            capital=1000.0
        )
        
        self.assertLessEqual(recommendation.stake_usdc, 500.0)


class TestCLOBIntegration(unittest.TestCase):
    """Test CLOB API integration"""
    
    @patch('main.ClobClient')
    def test_clob_connection_success(self, mock_client_class):
        """Test successful CLOB connection"""
        # Mock the client
        mock_client = Mock()
        mock_client.get_simplified_markets.return_value = {
            'data': [
                {
                    'question': 'Test Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.65', '0.35'],
                    'condition_id': 'test-123',
                    'description': 'Test description',
                    'end_date_iso': '2024-12-31'
                }
            ]
        }
        mock_client_class.return_value = mock_client
        
        result = test_clob_connection()
        
        # Verify the result
        self.assertTrue(result)
        # Verify the client was initialized with correct parameters
        mock_client_class.assert_called_once_with(host='https://clob.polymarket.com', chain_id=137)
        # Verify get_simplified_markets was called
        mock_client.get_simplified_markets.assert_called_once()
    
    @patch('main.ClobClient')
    def test_fetch_markets_with_filtering(self, mock_client_class):
        """Test market fetching with volume filtering"""
        # Mock the client
        mock_client = Mock()
        mock_client.get_simplified_markets.return_value = {
            'data': [
                {
                    'question': 'High Volume Market',
                    'active': True,
                    'volume': '50000',  # Above MIN_VOLUME (15000)
                    'outcome_prices': ['0.65', '0.35'],
                    'condition_id': 'test-123',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Low Volume Market',
                    'active': True,
                    'volume': '100',  # Below MIN_VOLUME (15000)
                    'outcome_prices': ['0.50', '0.50'],
                    'condition_id': 'test-456',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Inactive Market',
                    'active': False,  # Should be filtered out
                    'volume': '50000',
                    'outcome_prices': ['0.65', '0.35'],
                    'condition_id': 'test-789',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                }
            ]
        }
        mock_client_class.return_value = mock_client
        
        markets = fetch_active_markets(limit=10)
        
        # Should only return the high volume, active market
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].question, 'High Volume Market')
        self.assertEqual(markets[0].volume, 50000.0)

    @patch('main.ClobClient')
    def test_fetch_markets_without_volume_data(self, mock_client_class):
        """Test market fetching when volume data is not available"""
        # Mock the client with markets that don't have volume field
        mock_client = Mock()
        mock_client.get_simplified_markets.return_value = {
            'data': [
                {
                    'question': 'Market Without Volume',
                    'active': True,
                    # No volume field - mimics real CLOB API response
                    'outcome_prices': ['0.65', '0.35'],
                    'condition_id': 'test-123',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Another Market',
                    'active': True,
                    'outcome_prices': ['0.50', '0.50'],
                    'condition_id': 'test-456',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                }
            ]
        }
        mock_client_class.return_value = mock_client
        
        markets = fetch_active_markets(limit=10)
        
        # Should return both markets since volume filter is skipped when data unavailable
        self.assertEqual(len(markets), 2)
        # Volume should be set to 0 when not available
        self.assertEqual(markets[0].volume, 0.0)
        self.assertEqual(markets[1].volume, 0.0)

    @patch('main.ClobClient')
    def test_fetch_markets_with_zero_volume(self, mock_client_class):
        """Test that markets with actual zero volume are filtered out"""
        # Mock the client with a market that has volume field set to 0
        mock_client = Mock()
        mock_client.get_simplified_markets.return_value = {
            'data': [
                {
                    'question': 'Zero Volume Market',
                    'active': True,
                    'volume': '0',  # Volume is 0 - should be filtered
                    'outcome_prices': ['0.65', '0.35'],
                    'condition_id': 'test-123',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Good Volume Market',
                    'active': True,
                    'volume': '50000',  # Above MIN_VOLUME (15000)
                    'outcome_prices': ['0.50', '0.50'],
                    'condition_id': 'test-456',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                }
            ]
        }
        mock_client_class.return_value = mock_client
        
        markets = fetch_active_markets(limit=10)
        
        # Should only return the market with good volume
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].question, 'Good Volume Market')
        self.assertEqual(markets[0].volume, 50000.0)

    @patch('main.ClobClient')
    def test_fetch_markets_with_extreme_prices(self, mock_client_class):
        """Test that markets with extreme prices (outside 0.15-0.85) are filtered out"""
        # Mock the client with markets having extreme prices
        mock_client = Mock()
        mock_client.get_simplified_markets.return_value = {
            'data': [
                {
                    'question': 'Extreme High Price Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.95', '0.05'],  # Too high, should be filtered
                    'condition_id': 'test-123',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Extreme Low Price Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.05', '0.95'],  # Too low, should be filtered
                    'condition_id': 'test-456',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Good Price Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.50', '0.50'],  # Within range
                    'condition_id': 'test-789',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Edge Case High Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.85', '0.15'],  # Exactly at edge, should pass
                    'condition_id': 'test-101',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                },
                {
                    'question': 'Edge Case Low Market',
                    'active': True,
                    'volume': '50000',
                    'outcome_prices': ['0.15', '0.85'],  # Exactly at edge, should pass
                    'condition_id': 'test-102',
                    'description': 'Test',
                    'end_date_iso': '2024-12-31'
                }
            ]
        }
        mock_client_class.return_value = mock_client
        
        markets = fetch_active_markets(limit=10)
        
        # Should return only markets with prices in range (0.15-0.85)
        self.assertEqual(len(markets), 3)
        questions = [m.question for m in markets]
        self.assertIn('Good Price Market', questions)
        self.assertIn('Edge Case High Market', questions)
        self.assertIn('Edge Case Low Market', questions)
        self.assertNotIn('Extreme High Price Market', questions)
        self.assertNotIn('Extreme Low Price Market', questions)


if __name__ == '__main__':
    unittest.main()
