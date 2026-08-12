"""Yahoo Finance-backed market data tools."""

import math
import re
from typing import Any

import yfinance
from loguru import logger

from aria.tools import (
    Reason,
    get_function_name,
    log_tool_call,
    tool_error_response,
    tool_success_response,
    utc_timestamp,
)


class YFinanceError(Exception):
    """Custom exception for YFinance-related errors."""


class YFinanceValidationError(YFinanceError):
    """Exception for input validation errors."""


class YFinanceDataError(YFinanceError):
    """Exception for data retrieval errors."""


# Valid ticker symbol pattern (letters, numbers, dots, hyphens)
TICKER_PATTERN = re.compile(r"^[A-Z0-9.-]{1,10}$")

# Common quote currencies for crypto pairs where users often omit the dash.
# Examples:
# - BTCUSD -> BTC-USD
# - ETH/EUR -> ETH-EUR
_CRYPTO_QUOTE_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "AUD",
    "CAD",
}

# News article limits
MIN_ARTICLES = 1
MAX_ARTICLES = 50


@log_tool_call
def fetch_current_stock_price(reason: Reason, ticker: str) -> str:
    """Fetch the current price for a stock, ETF, or crypto ticker.

    Use this for price and day-change questions, not company fundamentals.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        ticker: Symbol such as ``AAPL`` or ``BTC-USD``.

    Returns:
        JSON with current price, currency, market state, and day change.
    """
    logger.info(f"fetch_current_stock_price called with ticker='{ticker}'")
    raw_ticker = ticker
    try:
        ticker = _validate_ticker(ticker)
        logger.debug(f"Ticker validated: {ticker}")

        ticker_obj = _get_ticker(ticker)
        logger.debug(f"Ticker object created for {ticker}")

        info = _get_ticker_info(ticker_obj, ticker)
        logger.debug(f"Ticker info retrieved, keys: {list(info.keys())[:10]}")

        # Try multiple price fields
        current_price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        )

        current_price = _finite_price(current_price)
        if current_price is None:
            raise YFinanceDataError(f"No price data available for {ticker}")

        # Get additional price context
        currency = info.get("currency", "USD")
        market_state = info.get("marketState", "UNKNOWN")

        result = {
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "currency": currency,
            "market_state": market_state,
            "timestamp": utc_timestamp(),
            "previous_close": info.get("previousClose"),
            "day_change": None,
            "day_change_percent": None,
        }

        # Calculate day change if possible
        prev_close = info.get("previousClose")
        if prev_close and current_price and prev_close != 0:
            day_change = current_price - prev_close
            day_change_percent = (day_change / prev_close) * 100
            result.update(
                {
                    "day_change": round(day_change, 2),
                    "day_change_percent": round(day_change_percent, 2),
                }
            )

        logger.info(
            f"Successfully fetched price for {ticker}: "
            f"${result['current_price']} {result['currency']}"
        )
        return tool_success_response(get_function_name(), reason, result)

    except YFinanceValidationError as exc:
        logger.error(f"Validation error for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="validation_error",
        )
    except YFinanceDataError as exc:
        logger.error(f"Data error for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="data_error",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Important: tools should never raise here; an exception can crash the
        # agent.
        logger.exception(f"Unexpected error fetching price for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            RuntimeError(f"Failed to get current price: {exc}"),
            ticker=raw_ticker,
            error_type="unexpected_error",
        )


@log_tool_call
def fetch_company_information(reason: Reason, ticker: str) -> str:
    """Fetch company fundamentals and metadata for a ticker.

    Use this for business, valuation, financial-health, or analyst questions,
    not simple price lookups.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        ticker: Stock symbol such as ``AAPL``.

    Returns:
        JSON bundle with company info, financial metrics, price data,
        analyst data, and location.
    """
    logger.info(f"fetch_company_information called with ticker='{ticker}'")
    raw_ticker = ticker
    try:
        ticker = _validate_ticker(ticker)
        logger.debug(f"Ticker validated: {ticker}")

        ticker_obj = _get_ticker(ticker)
        info = _get_ticker_info(ticker_obj, ticker)
        logger.debug(f"Retrieved company info for {ticker}")

        # Organize company information with safe extraction
        company_info = {
            "basic_info": {
                "name": info.get("shortName") or info.get("longName"),
                "symbol": info.get("symbol"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "website": info.get("website"),
                "summary": info.get("longBusinessSummary"),
                "employees": info.get("fullTimeEmployees"),
            },
            "financial_metrics": {
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "eps_trailing": info.get("trailingEps"),
                "eps_forward": info.get("forwardEps"),
            },
            "price_data": {
                "current_price": info.get("regularMarketPrice")
                or info.get("currentPrice"),
                "currency": info.get("currency", "USD"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_day_average": info.get("fiftyDayAverage"),
                "two_hundred_day_average": info.get("twoHundredDayAverage"),
            },
            "financial_health": {
                "total_cash": info.get("totalCash"),
                "total_debt": info.get("totalDebt"),
                "free_cashflow": info.get("freeCashflow"),
                "operating_cashflow": info.get("operatingCashflow"),
                "ebitda": info.get("ebitda"),
                "revenue_growth": info.get("revenueGrowth"),
                "gross_margins": info.get("grossMargins"),
                "ebitda_margins": info.get("ebitdaMargins"),
            },
            "analyst_data": {
                "recommendation_key": info.get("recommendationKey"),
                "recommendation_mean": info.get("recommendationMean"),
                "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
                "target_high_price": info.get("targetHighPrice"),
                "target_low_price": info.get("targetLowPrice"),
                "target_mean_price": info.get("targetMeanPrice"),
            },
            "location": {
                "address": info.get("address1"),
                "city": info.get("city"),
                "state": info.get("state"),
                "zip": info.get("zip"),
                "country": info.get("country"),
            },
            "metadata": {
                "ticker": ticker,
                "timestamp": utc_timestamp(),
                "data_source": "Yahoo Finance",
            },
        }

        logger.info(
            f"Successfully fetched company info for {ticker}: "
            f"{company_info['basic_info'].get('name', 'Unknown')}"
        )
        return tool_success_response(get_function_name(), reason, company_info)

    except YFinanceValidationError as exc:
        logger.error(f"Validation error for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="validation_error",
        )
    except YFinanceDataError as exc:
        logger.error(f"Data error for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="data_error",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception(
            f"Unexpected error fetching company info for {raw_ticker}: {exc}"
        )
        return tool_error_response(
            get_function_name(),
            reason,
            RuntimeError(f"Failed to get company information: {exc}"),
            ticker=raw_ticker,
            error_type="unexpected_error",
        )


@log_tool_call
def fetch_ticker_news(reason: Reason, ticker: str, max_articles: int = 10) -> str:
    """Fetch recent news for a stock or crypto ticker.

    Use this for recent-events or sentiment questions, not fundamentals.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        ticker: Stock symbol such as ``AAPL``.
        max_articles: Maximum number of articles to return.

    Returns:
        JSON with recent article metadata.
    """
    logger.info(
        f"fetch_ticker_news called with ticker='{ticker}', max_articles={max_articles}"
    )
    raw_ticker = ticker
    try:
        ticker = _validate_ticker(ticker)
        logger.debug(f"Ticker validated: {ticker}")

        if not isinstance(max_articles, int):
            raise YFinanceValidationError("max_articles must be an integer")

        max_articles = max(MIN_ARTICLES, min(MAX_ARTICLES, max_articles))
        logger.debug(f"Max articles set to: {max_articles}")

        ticker_obj = _get_ticker(ticker)

        try:
            news_data = ticker_obj.news
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise YFinanceDataError(f"Failed to fetch news data: {exc}") from exc

        if not news_data:
            return tool_success_response(
                get_function_name(),
                reason,
                {
                    "ticker": ticker,
                    "articles": [],
                    "count": 0,
                    "message": "No news articles found",
                    "timestamp": utc_timestamp(),
                },
            )

        articles = []
        for article in news_data[:max_articles]:
            processed = _process_news_article(article)
            if processed:
                articles.append(processed)

        result = {
            "ticker": ticker,
            "articles": articles,
            "count": len(articles),
            "timestamp": utc_timestamp(),
        }

        logger.info(f"Successfully fetched {len(articles)} news articles for {ticker}")
        return tool_success_response(get_function_name(), reason, result)

    except YFinanceValidationError as exc:
        logger.error(f"Validation error for {raw_ticker} news: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="validation_error",
            articles=[],
            count=0,
        )
    except YFinanceDataError as exc:
        logger.error(f"Data error for {raw_ticker} news: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            exc,
            ticker=raw_ticker,
            error_type="data_error",
            articles=[],
            count=0,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception(f"Unexpected error fetching news for {raw_ticker}: {exc}")
        return tool_error_response(
            get_function_name(),
            reason,
            RuntimeError(f"Failed to get news: {exc}"),
            ticker=raw_ticker,
            error_type="unexpected_error",
            articles=[],
            count=0,
        )


def _finite_price(value: Any) -> float | None:
    """Return value as a finite float, or None if it is not a usable price.

    Rejects None, NaN, and inf, which would otherwise serialise to invalid
    JSON tokens (``NaN``, ``Infinity``) via ``safe_json``.

    Args:
        value: The candidate price value from ticker info.

    Returns:
        Price as a finite float, or None if not usable.
    """
    if value is None:
        return None
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _validate_ticker(ticker: Any) -> str:
    """
    Validate and normalize ticker symbol.

    Args:
        ticker (str): Raw ticker symbol

    Returns:
        Normalized ticker symbol
    """
    if ticker is None:
        raise YFinanceValidationError("Ticker symbol cannot be empty")
    if not isinstance(ticker, str):
        raise YFinanceValidationError("Ticker symbol must be a string")

    ticker = _normalize_ticker(ticker)

    if not ticker:
        raise YFinanceValidationError(
            "Ticker symbol cannot be empty after normalization"
        )

    if not TICKER_PATTERN.match(ticker):
        raise YFinanceValidationError(f"Invalid ticker symbol format: {ticker}")

    return ticker


def _normalize_ticker(ticker: str) -> str:
    """Normalize common user-entered ticker variants.

    This helps map user input to Yahoo Finance formats.
    """
    # Normalize ticker (uppercase, strip whitespace)
    normalized = str(ticker).strip().upper()

    # Support common pair delimiters for crypto/FX inputs.
    # BTC/USD -> BTC-USD
    if "/" in normalized:
        normalized = normalized.replace("/", "-")

    # Crypto pairs are commonly entered without a dash.
    # BTCUSD -> BTC-USD
    if "-" not in normalized:
        for quote in _CRYPTO_QUOTE_CURRENCIES:
            if normalized.endswith(quote) and len(normalized) > len(quote):
                base = normalized[: -len(quote)]
                if 2 <= len(base) <= 6:
                    normalized = f"{base}-{quote}"
                break

    return normalized


def _get_ticker(ticker: str) -> Any:
    """Get yfinance Ticker object."""
    return yfinance.Ticker(ticker)


def _get_ticker_info(ticker_obj: Any, ticker: str) -> dict[str, Any]:
    """
    Get ticker info with error handling.

    Args:
        ticker_obj: YFinance Ticker object
        ticker: Ticker symbol for error messages

    Returns:
        Ticker info dictionary
    """
    try:
        info = ticker_obj.info
        if not info or not isinstance(info, dict):
            raise YFinanceDataError(f"No information available for {ticker}")
        return info
    except Exception as exc:
        raise YFinanceDataError(
            f"Failed to get ticker info for {ticker}: {exc}"
        ) from exc


def _process_news_article(article: Any) -> dict[str, Any] | None:
    """
    Process a single news article into standardized format.

    Args:
        article: Raw article data from yfinance

    Returns:
        Processed article dict or None if processing fails
    """
    try:
        if not isinstance(article, dict):
            return None

        if "content" in article:
            # New format
            content = article["content"]
            canonical_url = content.get("canonicalUrl", {})
            url = (
                canonical_url.get("url", "") if isinstance(canonical_url, dict) else ""
            )
            return {
                "title": content.get("title", "No title"),
                "summary": content.get("summary", ""),
                "published_date": content.get("pubDate", ""),
                "url": url,
                "source": article.get("source", "Unknown"),
            }
        else:
            # Direct format
            return {
                "title": article.get("title", "No title"),
                "summary": article.get("summary", ""),
                "published_date": article.get("providerPublishTime", ""),
                "url": article.get("link", ""),
                "source": article.get("publisher", "Unknown"),
            }
    except (KeyError, TypeError, ValueError):
        return None
