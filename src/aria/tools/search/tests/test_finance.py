"""
Test suite for Yahoo Finance data retrieval module.

Tests cover:
- Ticker validation
- Stock price fetching
- Company information retrieval
- News article fetching
- Error handling
- Edge cases
"""

import json
from datetime import datetime
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest

from aria.tools.search.finance import (
    MAX_ARTICLES,
    MIN_ARTICLES,
    YFinanceDataError,
    YFinanceError,
    YFinanceValidationError,
    _get_ticker,
    _get_ticker_info,
    _process_news_article,
    _validate_ticker,
    fetch_company_information,
    fetch_current_stock_price,
    fetch_ticker_news,
)


def _response_data(raw: str) -> dict:
    payload = json.loads(raw)
    return payload["data"]


def _response_error(raw: str) -> str:
    payload = json.loads(raw)
    return payload["error"]["message"]


def _response_context(raw: str) -> dict:
    payload = json.loads(raw)
    return payload.get("context", {})


# ============================================================================
# Ticker Validation Tests
# ============================================================================


class TestTickerValidation:
    """Test ticker symbol validation."""

    def test_validate_ticker_success(self):
        """Test valid ticker symbols."""
        assert _validate_ticker("AAPL") == "AAPL"
        assert _validate_ticker("aapl") == "AAPL"
        assert _validate_ticker("  AAPL  ") == "AAPL"
        assert _validate_ticker("BRK.B") == "BRK.B"
        assert _validate_ticker("BRK-B") == "BRK-B"
        assert _validate_ticker("MSFT") == "MSFT"

    def test_validate_ticker_empty(self):
        """Test empty ticker validation."""
        with pytest.raises(YFinanceValidationError, match="cannot be empty"):
            _validate_ticker("")

        with pytest.raises(YFinanceValidationError, match="cannot be empty"):
            _validate_ticker("   ")

    def test_validate_ticker_invalid_type(self):
        """Test invalid ticker types."""
        with pytest.raises(YFinanceValidationError, match="cannot be empty"):
            _validate_ticker(None)

        with pytest.raises(YFinanceValidationError, match="must be a string"):
            _validate_ticker(123)

    def test_validate_ticker_invalid_format(self):
        """Test invalid ticker formats."""
        with pytest.raises(
            YFinanceValidationError, match="Invalid ticker symbol format"
        ):
            _validate_ticker("AAPL@")

        with pytest.raises(
            YFinanceValidationError, match="Invalid ticker symbol format"
        ):
            _validate_ticker("A" * 11)  # Too long

        with pytest.raises(
            YFinanceValidationError, match="Invalid ticker symbol format"
        ):
            _validate_ticker("AAPL MSFT")  # Space not allowed


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestHelperFunctions:
    """Test helper functions."""

    def test_get_ticker(self):
        """Test _get_ticker returns yfinance Ticker object."""
        with patch("aria.tools.search.finance.yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value = Mock()
            result = _get_ticker("AAPL")
            mock_ticker.assert_called_once_with("AAPL")
            assert result is not None

    def test_get_ticker_info_success(self):
        """Test successful ticker info retrieval."""
        mock_ticker = Mock()
        mock_ticker.info = {"symbol": "AAPL", "price": 150.0}

        result = _get_ticker_info(mock_ticker, "AAPL")
        assert result == {"symbol": "AAPL", "price": 150.0}

    def test_get_ticker_info_empty(self):
        """Test ticker info with empty data."""
        mock_ticker = Mock()
        mock_ticker.info = {}

        with pytest.raises(YFinanceDataError, match="No information available"):
            _get_ticker_info(mock_ticker, "AAPL")

    def test_get_ticker_info_not_dict(self):
        """Test ticker info with non-dict data."""
        mock_ticker = Mock()
        mock_ticker.info = None

        with pytest.raises(YFinanceDataError, match="No information available"):
            _get_ticker_info(mock_ticker, "AAPL")

    def test_get_ticker_info_exception(self):
        """Test ticker info with exception."""
        mock_ticker = Mock()
        mock_ticker.info = property(
            lambda self: (_ for _ in ()).throw(Exception("Network error"))
        )

        with pytest.raises(YFinanceDataError, match="Failed to get ticker info"):
            _get_ticker_info(mock_ticker, "AAPL")

    # ============================================================================
    # News Article Processing Tests
    # ============================================================================


class TestNewsArticleProcessing:
    """Test news article processing."""

    def test_process_news_article_new_format(self):
        """Test processing article in new format."""
        article = {
            "content": {
                "title": "Test Title",
                "summary": "Test Summary",
                "pubDate": "2024-01-01",
                "canonicalUrl": {"url": "https://example.com"},
            },
            "source": "Test Source",
        }

        result = _process_news_article(article)
        assert result is not None
        assert result["title"] == "Test Title"
        assert result["summary"] == "Test Summary"
        assert result["published_date"] == "2024-01-01"
        assert result["url"] == "https://example.com"
        assert result["source"] == "Test Source"

    def test_process_news_article_direct_format(self):
        """Test processing article in direct format."""
        article = {
            "title": "Direct Title",
            "summary": "Direct Summary",
            "providerPublishTime": "2024-01-01",
            "link": "https://example.com",
            "publisher": "Direct Publisher",
        }

        result = _process_news_article(article)
        assert result is not None
        assert result["title"] == "Direct Title"
        assert result["summary"] == "Direct Summary"
        assert result["published_date"] == "2024-01-01"
        assert result["url"] == "https://example.com"
        assert result["source"] == "Direct Publisher"

    def test_process_news_article_missing_fields(self):
        """Test processing article with missing fields."""
        article = {"content": {}}

        result = _process_news_article(article)
        assert result is not None
        assert result["title"] == "No title"
        assert result["summary"] == ""

    def test_process_news_article_invalid_type(self):
        """Test processing non-dict article."""
        assert _process_news_article(None) is None
        assert _process_news_article("string") is None
        assert _process_news_article([]) is None

    def test_process_news_article_exception(self):
        """Test processing article that raises exception."""
        article = {"content": {"canonicalUrl": "not a dict"}}
        result = _process_news_article(article)
        # Should handle gracefully
        assert result is not None


# ============================================================================
# Stock Price Fetching Tests
# ============================================================================


class TestFetchCurrentStockPrice:
    """Test fetch_current_stock_price function."""

    def test_fetch_price_success(self):
        """Test successful price fetch."""
        mock_info = {
            "regularMarketPrice": 150.25,
            "currency": "USD",
            "marketState": "REGULAR",
            "previousClose": 148.50,
        }

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["ticker"] == "AAPL"
            assert result_dict["current_price"] == 150.25
            assert result_dict["currency"] == "USD"
            assert result_dict["market_state"] == "REGULAR"
            assert result_dict["previous_close"] == 148.50
            assert result_dict["day_change"] == 1.75
            assert "timestamp" in result_dict

    def test_fetch_price_alternative_fields(self):
        """Test price fetch with alternative price fields."""
        mock_info = {
            "currentPrice": 150.25,
            "currency": "USD",
            "marketState": "CLOSED",
        }

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["current_price"] == 150.25

    def test_fetch_price_no_price_data(self):
        """Test price fetch with no price data."""
        mock_info = {"currency": "USD"}

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            context = _response_context(result)
            assert context["ticker"] == "AAPL"
            assert context["error_type"] == "data_error"
            assert "No price data available" in _response_error(result)

    def test_fetch_price_invalid_ticker(self):
        """Test price fetch with invalid ticker."""
        result = fetch_current_stock_price("Testing stock price", "INVALID@TICKER")
        context = _response_context(result)
        assert context["ticker"] == "INVALID@TICKER"
        assert context["error_type"] == "validation_error"
        assert "Invalid ticker symbol format" in _response_error(result)

    def test_fetch_price_day_change_calculation(self):
        """Test day change percentage calculation."""
        mock_info = {
            "regularMarketPrice": 100.0,
            "previousClose": 90.0,
            "currency": "USD",
        }

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["day_change"] == 10.0
            assert result_dict["day_change_percent"] == pytest.approx(11.11, 0.01)

    def test_fetch_price_no_previous_close(self):
        """Test price fetch without previous close."""
        mock_info = {
            "regularMarketPrice": 150.25,
            "currency": "USD",
        }

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["day_change"] is None
            assert result_dict["day_change_percent"] is None

    def test_nan_price_returns_error_and_valid_json(self):
        """A NaN price must not succeed and must not emit invalid JSON."""
        mock_info = {"regularMarketPrice": float("nan"), "currency": "USD"}

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")

            # Must be strict JSON (no NaN/Infinity tokens)
            json.loads(
                result,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
            )

            context = _response_context(result)
            assert context["ticker"] == "AAPL"
            assert context["error_type"] == "data_error"
            assert "No price data available" in _response_error(result)

    def test_inf_price_returns_error_and_valid_json(self):
        """An infinite price must not succeed and must not emit invalid JSON."""
        mock_info = {"regularMarketPrice": float("inf"), "currency": "USD"}

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")

            json.loads(
                result,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
            )

            context = _response_context(result)
            assert context["ticker"] == "AAPL"
            assert context["error_type"] == "data_error"


# ============================================================================
# Company Information Tests
# ============================================================================


class TestFetchCompanyInformation:
    """Test fetch_company_information function."""

    def test_fetch_company_info_success(self):
        """Test successful company info fetch."""
        mock_info = {
            "shortName": "Apple Inc.",
            "symbol": "AAPL",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "website": "https://www.apple.com",
            "longBusinessSummary": "Apple designs and manufactures...",
            "fullTimeEmployees": 164000,
            "marketCap": 3000000000000,
            "regularMarketPrice": 150.25,
            "currency": "USD",
            "city": "Cupertino",
            "state": "CA",
            "country": "United States",
        }

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_company_information("Testing company info", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["basic_info"]["name"] == "Apple Inc."
            assert result_dict["basic_info"]["symbol"] == "AAPL"
            assert result_dict["basic_info"]["sector"] == "Technology"
            assert result_dict["financial_metrics"]["market_cap"] == 3000000000000
            assert result_dict["price_data"]["current_price"] == 150.25
            assert result_dict["location"]["city"] == "Cupertino"
            assert result_dict["metadata"]["ticker"] == "AAPL"
            assert "timestamp" in result_dict["metadata"]

    def test_fetch_company_info_minimal_data(self):
        """Test company info with minimal data."""
        mock_info = {"symbol": "TEST"}

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_company_information("Testing company info", "TEST")
            result_dict = _response_data(result)

            assert result_dict["basic_info"]["symbol"] == "TEST"
            assert result_dict["basic_info"]["name"] is None
            assert result_dict["metadata"]["ticker"] == "TEST"

    def test_fetch_company_info_invalid_ticker(self):
        """Test company info with invalid ticker."""
        result = fetch_company_information("Testing company info", "")
        context = _response_context(result)
        assert context["ticker"] == ""
        assert context["error_type"] == "validation_error"
        assert "cannot be empty" in _response_error(result)


# ============================================================================
# News Fetching Tests
# ============================================================================


class TestFetchTickerNews:
    """Test fetch_ticker_news function."""

    def test_fetch_news_success(self):
        """Test successful news fetch."""
        mock_news = [
            {
                "title": "Apple announces new product",
                "summary": "Apple has announced...",
                "providerPublishTime": "2024-01-01",
                "link": "https://example.com/1",
                "publisher": "Tech News",
            },
            {
                "title": "Apple stock rises",
                "summary": "Apple stock has risen...",
                "providerPublishTime": "2024-01-02",
                "link": "https://example.com/2",
                "publisher": "Finance News",
            },
        ]

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.news = mock_news
            mock_get_ticker.return_value = mock_ticker

            result = fetch_ticker_news("Testing ticker news", "AAPL", max_articles=2)
            result_dict = _response_data(result)

            assert result_dict["ticker"] == "AAPL"
            assert result_dict["count"] == 2
            assert len(result_dict["articles"]) == 2
            assert result_dict["articles"][0]["title"] == "Apple announces new product"
            assert "timestamp" in result_dict

    def test_fetch_news_no_articles(self):
        """Test news fetch with no articles."""
        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.news = []
            mock_get_ticker.return_value = mock_ticker

            result = fetch_ticker_news("Testing ticker news", "AAPL")
            result_dict = _response_data(result)

            assert result_dict["ticker"] == "AAPL"
            assert result_dict["count"] == 0
            assert result_dict["articles"] == []
            assert "No news articles found" in result_dict["message"]

    def test_fetch_news_max_articles_limit(self):
        """Test news fetch respects max_articles limit."""
        mock_news = [
            {
                "title": f"Article {i}",
                "summary": f"Summary {i}",
                "link": f"https://example.com/{i}",
                "publisher": "News",
            }
            for i in range(100)
        ]

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.news = mock_news
            mock_get_ticker.return_value = mock_ticker

            result = fetch_ticker_news("Testing ticker news", "AAPL", max_articles=5)
            result_dict = _response_data(result)

            assert result_dict["count"] == 5
            assert len(result_dict["articles"]) == 5

    def test_fetch_news_max_articles_bounds(self):
        """Test max_articles is bounded by MIN and MAX constants."""
        mock_news = [{"title": "Test", "link": "https://example.com"}]

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.news = mock_news
            mock_get_ticker.return_value = mock_ticker

            # Test lower bound
            result = fetch_ticker_news("Testing ticker news", "AAPL", max_articles=-5)
            result_dict = _response_data(result)
            assert result_dict["count"] >= 0

            # Test upper bound
            result = fetch_ticker_news("Testing ticker news", "AAPL", max_articles=1000)
            result_dict = _response_data(result)
            assert result_dict["count"] <= MAX_ARTICLES

    def test_fetch_news_invalid_max_articles_type(self):
        """Test news fetch with invalid max_articles type."""
        result = fetch_ticker_news(
            "Testing ticker news", "AAPL", max_articles=cast(Any, "10")
        )
        context = _response_context(result)
        assert context["ticker"] == "AAPL"
        assert context["error_type"] == "validation_error"
        assert "max_articles must be an integer" in _response_error(result)
        assert context["articles"] == []
        assert context["count"] == 0

        result = fetch_ticker_news(
            "Testing ticker news", "AAPL", max_articles=cast(Any, 10.5)
        )
        context = _response_context(result)
        assert context["ticker"] == "AAPL"
        assert context["error_type"] == "validation_error"
        assert "max_articles must be an integer" in _response_error(result)
        assert context["articles"] == []
        assert context["count"] == 0

    def test_fetch_news_invalid_ticker(self):
        """Test news fetch with invalid ticker."""
        result = fetch_ticker_news("Testing ticker news", "")
        context = _response_context(result)
        assert context["ticker"] == ""
        assert context["error_type"] == "validation_error"
        assert "cannot be empty" in _response_error(result)
        assert context["articles"] == []
        assert context["count"] == 0

    def test_fetch_news_api_exception(self):
        """Test news fetch with API exception."""
        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            # Configure news property to raise exception when accessed
            type(mock_ticker).news = property(
                lambda self: (_ for _ in ()).throw(Exception("API Error"))
            )
            mock_get_ticker.return_value = mock_ticker

            result = fetch_ticker_news("Testing ticker news", "AAPL")
            context = _response_context(result)
            assert context["ticker"] == "AAPL"
            assert context["error_type"] == "data_error"
            assert "Failed to fetch news data" in _response_error(result)
            assert context["articles"] == []
            assert context["count"] == 0

    def test_fetch_news_malformed_articles(self):
        """Test news fetch with some malformed articles."""
        mock_news = [
            {
                "title": "Good Article",
                "link": "https://example.com/1",
                "publisher": "News",
            },
            None,  # Malformed
            "invalid",  # Malformed
            {
                "title": "Another Good Article",
                "link": "https://example.com/2",
                "publisher": "News",
            },
        ]

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.news = mock_news
            mock_get_ticker.return_value = mock_ticker

            result = fetch_ticker_news("Testing ticker news", "AAPL", max_articles=10)
            result_dict = _response_data(result)

            # Should only include valid articles
            assert result_dict["count"] == 2
            assert len(result_dict["articles"]) == 2


# ============================================================================
# Exception Hierarchy Tests
# ============================================================================


class TestExceptionHierarchy:
    """Test custom exception hierarchy."""

    def test_exception_inheritance(self):
        """Test exception inheritance."""
        assert issubclass(YFinanceValidationError, YFinanceError)
        assert issubclass(YFinanceDataError, YFinanceError)
        assert issubclass(YFinanceError, Exception)

    def test_exception_messages(self):
        """Test exception messages."""
        exc = YFinanceValidationError("Invalid ticker")
        assert str(exc) == "Invalid ticker"

        exc = YFinanceDataError("Data not found")
        assert str(exc) == "Data not found"


# ============================================================================
# Integration-like Tests
# ============================================================================


class TestIntegration:
    """Integration-like tests with more realistic scenarios."""

    def test_full_stock_price_workflow(self):
        """Test complete stock price workflow."""
        mock_info = {
            "regularMarketPrice": 175.50,
            "currency": "USD",
            "marketState": "REGULAR",
            "previousClose": 173.25,
        }

        with patch("aria.tools.search.finance.yfinance.Ticker") as mock_ticker_class:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_ticker_class.return_value = mock_ticker

            result = fetch_current_stock_price(
                "Testing stock price", "aapl"
            )  # lowercase
            result_dict = _response_data(result)

            assert result_dict["ticker"] == "AAPL"  # normalized
            assert result_dict["current_price"] == 175.50
            assert result_dict["day_change"] == 2.25

    def test_timestamp_format(self):
        """Test that timestamps are in ISO format with UTC."""
        mock_info = {"regularMarketPrice": 150.0, "currency": "USD"}

        with patch("aria.tools.search.finance._get_ticker") as mock_get_ticker:
            mock_ticker = Mock()
            mock_ticker.info = mock_info
            mock_get_ticker.return_value = mock_ticker

            result = fetch_current_stock_price("Testing stock price", "AAPL")
            result_dict = _response_data(result)

            # Should be valid ISO format
            timestamp = result_dict["timestamp"]
            parsed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            assert isinstance(parsed_time, datetime)


# ============================================================================
# Constants Tests
# ============================================================================


class TestConstants:
    """Test module constants."""

    def test_article_limits(self):
        """Test article limit constants."""
        assert MIN_ARTICLES == 1
        assert MAX_ARTICLES == 50
        assert MIN_ARTICLES < MAX_ARTICLES
