#!/usr/bin/env python3
"""
Test suite for Polymarket AI Value Bet Bot
Tests the core functionality with mock data
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pydantic import ValidationError
from src.main import (
    MarketData, 
    AIAnalysis, 
    TradingRecommendation,
    calculate_kelly_stake,
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
            url_slug="test-market",
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
            ai_prob=0.7,
            price=0.5,
            conf=0.9,
            capital=1000.0
        )
        
        self.assertEqual(recommendation.action, "YES")
        self.assertGreater(recommendation.stake_usdc, 0)
        self.assertLessEqual(recommendation.stake_usdc, 500)  # Max 50% of capital
        self.assertGreater(recommendation.expected_value, 0)
    
    def test_kelly_with_negative_edge(self):
        """Test Kelly calculation with negative edge (should recommend NO or PASS)"""
        recommendation = calculate_kelly_stake(
            ai_prob=0.3,
            price=0.5,
            conf=0.9,
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
            ai_prob=0.99,
            price=0.1,
            conf=1.0,
            capital=1000.0
        )
        
        self.assertLessEqual(recommendation.stake_usdc, 500.0)


class TestGammaAPIIntegration(unittest.TestCase):
    """Test Gamma API integration"""
    
    @patch('src.main.requests.get')
    def test_fetch_markets_success(self, mock_get):
        """Test successful market fetching from Gamma API"""
        # Mock the response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'question': 'Test Market',
                'description': 'Test description',
                'id': 'test-123',
                'slug': 'test-market',
                'volume': '50000',
                'close_time': '2030-12-31T23:59:59Z',
                'outcome_prices': '["0.65", "0.35"]',
                'outcomes': '["Yes", "No"]'
            }
        ]
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Verify the result
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].question, 'Test Market')
        self.assertEqual(markets[0].yes_price, 0.65)
        self.assertEqual(markets[0].volume, 50000.0)
        self.assertEqual(markets[0].market_slug, 'test-123')
        
        # Verify the API was called correctly
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertEqual(call_args[0][0], 'https://gamma-api.polymarket.com/markets')
        self.assertIn('params', call_args[1])
        self.assertEqual(call_args[1]['params']['closed'], 'false')
    
    @patch('src.main.requests.get')
    def test_fetch_markets_with_filtering(self, mock_get):
        """Test market fetching with volume and price filtering"""
        # Mock the response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'question': 'High Volume Market',
                'description': 'Test',
                'id': 'test-123',
                'slug': 'high-volume',
                'volume': '50000',
                'close_time': '2030-12-31T23:59:59Z',
                'outcome_prices': '["0.65", "0.35"]',
                'outcomes': '["Yes", "No"]'
            },
            {
                'question': 'Extreme Price Market',
                'description': 'Test',
                'id': 'test-456',
                'slug': 'extreme-price',
                'volume': '40000',  # Less than HIGH_VOLUME_THRESHOLD (50000) so price filter applies
                'close_time': '2030-12-31T23:59:59Z',
                'outcome_prices': '["0.99", "0.01"]',  # Price too extreme (>0.95)
                'outcomes': '["Yes", "No"]'
            },
            {
                'question': 'Low Volume Market',
                'description': 'Test',
                'id': 'test-789',
                'slug': 'low-volume',
                'volume': '5000',  # Below MIN_VOLUME (10000)
                'close_time': '2030-12-31T23:59:59Z',
                'outcome_prices': '["0.50", "0.50"]',
                'outcomes': '["Yes", "No"]'
            }
        ]
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Should only return the market with acceptable price and volume
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].question, 'High Volume Market')
    
    @patch('src.main.requests.get')
    def test_fetch_markets_error_response(self, mock_get):
        """Test handling of error responses with errors field"""
        # Mock an error response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'errors': [{'message': 'API error'}]
        }
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Should return empty list on error (no markets in response)
        self.assertEqual(len(markets), 0)
    
    @patch('src.main.requests.get')
    def test_fetch_markets_http_error(self, mock_get):
        """Test handling of HTTP errors"""
        # Mock an HTTP error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Should return empty list on error
        self.assertEqual(len(markets), 0)
    
    @patch('src.main.requests.get')
    def test_fetch_markets_connection_error(self, mock_get):
        """Test handling of connection errors"""
        # Mock a connection error
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Network error")
        
        markets = fetch_active_markets(limit=10)
        
        # Should return empty list on error
        self.assertEqual(len(markets), 0)
    
    @patch('src.main.requests.get')
    def test_fetch_markets_with_list_outcome_prices(self, mock_get):
        """Test market fetching when outcome_prices is already a list"""
        # Mock the response with outcome_prices as list instead of string
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'question': 'Test Market',
                'description': 'Test',
                'id': 'test-123',
                'slug': 'test',
                'volume': '50000',
                'close_time': '2030-12-31T23:59:59Z',
                'outcome_prices': [0.65, 0.35],  # List instead of JSON string
                'outcomes': '["Yes", "No"]'
            }
        ]
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Should successfully parse list format
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].yes_price, 0.65)
    
    @patch('src.main.requests.get')
    def test_fetch_markets_expired(self, mock_get):
        """Test that expired markets are filtered out"""
        # Mock the response with an expired market
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'question': 'Expired Market',
                'description': 'Test',
                'id': 'test-123',
                'slug': 'expired',
                'volume': '50000',
                'close_time': '2020-01-01T00:00:00Z',  # Expired
                'outcome_prices': '["0.65", "0.35"]',
                'outcomes': '["Yes", "No"]'
            },
            {
                'question': 'Active Market',
                'description': 'Test',
                'id': 'test-456',
                'slug': 'active',
                'volume': '50000',
                'close_time': '2030-12-31T23:59:59Z',  # Future
                'outcome_prices': '["0.50", "0.50"]',
                'outcomes': '["Yes", "No"]'
            }
        ]
        mock_get.return_value = mock_response
        
        markets = fetch_active_markets(limit=10)
        
        # Should only return the active market
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].question, 'Active Market')


if __name__ == '__main__':
    unittest.main()
