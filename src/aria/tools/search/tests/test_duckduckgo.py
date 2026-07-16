import json
from unittest.mock import MagicMock, patch

import pytest

from aria.tools.search.duckduckgo import duckduckgo_web_search


def test_web_search_success():
    """Test successful web search with mock DDGS response"""
    mock_results = [
        {
            "title": "Elon Musk Is a Far-Right Activist - The Atlantic",
            "href": "https://www.theatlantic.com/technology/archive/2022/12/elon-musk-twitter-far-right-activist/672436/",
            "body": "... who share Musk 's pet ideological issues: that the mainstream media is ethically bankrupt, that social media and most elite institutions are biased ...",
        },
        {
            "title": "Elon Musk Is President - The Atlantic",
            "href": "https://www.theatlantic.com/politics/archive/2025/02/president-elon-musk-trump/681558/",
            "body": "... Bessent granted DOGE staffers access to the system that sends out money on behalf of the entire federal government, ceding to Musk —whose wealth is ...",
        },
    ]

    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = mock_results

        result = duckduckgo_web_search("Testing web search", "elon musk", max_results=2)
        result_dict = json.loads(result)

        assert result_dict["tool"] == "duckduckgo_web_search"
        assert result_dict["status"] == "success"
        assert len(result_dict["data"]["results"]) == 2
        assert "timestamp" in result_dict

        # Check first result
        assert (
            result_dict["data"]["results"][0]["title"]
            == "Elon Musk Is a Far-Right Activist - The Atlantic"
        )
        assert (
            result_dict["data"]["results"][0]["url"]
            == "https://www.theatlantic.com/technology/archive/2022/12/elon-musk-twitter-far-right-activist/672436/"
        )


def test_web_search_empty_query():
    """Test web search with empty query"""
    result = duckduckgo_web_search("Testing web search", "")
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid query" in result_dict["error"]["message"]


def test_web_search_invalid_max_results():
    """Test web search with invalid max_results"""
    result = duckduckgo_web_search("Testing web search", "test query", max_results=-5)
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid max_results" in result_dict["error"]["message"]


def test_web_search_exception_handling():
    """Test web search with exception handling"""
    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.side_effect = Exception("Network error")

        result = duckduckgo_web_search("Testing web search", "test query")
        result_dict = json.loads(result)

        assert result_dict["tool"] == "duckduckgo_web_search"
        assert result_dict["status"] == "error"
        assert "Network error" in result_dict["error"]["message"]


def test_web_search_default_max_results():
    """Test web search with default max_results"""
    mock_results = [
        {
            "title": "Test Result 1",
            "href": "https://example.com/1",
            "body": "Test body 1",
        }
    ]

    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = mock_results

        result = duckduckgo_web_search(
            "Testing web search", "test query"
        )  # No max_results specified
        result_dict = json.loads(result)

        assert result_dict["tool"] == "duckduckgo_web_search"
        assert result_dict["status"] == "success"
        assert len(result_dict["data"]["results"]) == 1
        assert result_dict["data"]["results"][0]["title"] == "Test Result 1"


def test_web_search_whitespace_only_query():
    """Test web search with whitespace-only query"""
    result = duckduckgo_web_search("Testing web search", "   ")
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid query" in result_dict["error"]["message"]


def test_web_search_query_with_leading_trailing_whitespace():
    """Test that query is properly stripped of whitespace"""
    mock_results = [
        {
            "title": "Test Result",
            "href": "https://example.com",
            "body": "Test body",
        }
    ]

    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = mock_results

        result = duckduckgo_web_search(
            "Testing web search", "  test query  ", max_results=1
        )
        result_dict = json.loads(result)

        # Verify the query was stripped before being passed to DDGS
        mock_search_instance.text.assert_called_once_with(
            query="test query", max_results=1
        )
        assert result_dict["status"] == "success"
        assert len(result_dict["data"]["results"]) == 1


def test_web_search_zero_max_results():
    """Test web search with max_results=0"""
    result = duckduckgo_web_search("Testing web search", "test query", max_results=0)
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid max_results" in result_dict["error"]["message"]


def test_web_search_non_integer_max_results():
    """Test web search with non-integer max_results"""
    result = duckduckgo_web_search("Testing web search", "test query", max_results="5")
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid max_results" in result_dict["error"]["message"]


def test_web_search_empty_results():
    """Test web search that returns no results"""
    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = []

        result = duckduckgo_web_search(
            "Testing web search", "very obscure query", max_results=5
        )
        result_dict = json.loads(result)

        assert result_dict["tool"] == "duckduckgo_web_search"
        assert result_dict["status"] == "success"
        assert result_dict["data"]["results"] == []


def test_web_search_result_structure():
    """Test that results only contain title and url (not body)"""
    mock_results = [
        {
            "title": "Test Title",
            "href": "https://example.com",
            "body": "This should not be in the output",
            "extra_field": "This should also not be in the output",
        }
    ]

    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = mock_results

        result = duckduckgo_web_search("Testing web search", "test", max_results=1)
        result_dict = json.loads(result)

        assert len(result_dict["data"]["results"]) == 1
        result_item = result_dict["data"]["results"][0]
        assert "title" in result_item
        assert "url" in result_item
        assert "body" not in result_item
        assert "extra_field" not in result_item
        assert len(result_item) == 2  # Only title and url


def test_web_search_json_format():
    """Test that the response is valid JSON with correct structure"""
    mock_results = [{"title": "Test", "href": "https://example.com", "body": "Body"}]

    with patch("aria.tools.search.duckduckgo.DDGS") as mock_ddgs:
        mock_search_instance = MagicMock()
        mock_ddgs.return_value = mock_search_instance
        mock_search_instance.text.return_value = mock_results

        result = duckduckgo_web_search("Testing web search", "test")

        # Should be valid JSON
        result_dict = json.loads(result)

        # Check top-level structure (Standard Envelope)
        assert "tool" in result_dict
        assert "status" in result_dict
        assert "data" in result_dict
        assert "timestamp" in result_dict

        # Check data structure
        assert "results" in result_dict["data"]

        # Check result is a list
        assert isinstance(result_dict["data"]["results"], list)


@pytest.mark.parametrize(
    "invalid_query",
    [
        None,
        123,
        [],
        {},
        False,
    ],
)
def test_web_search_invalid_query_types(invalid_query):
    """Test web search with various invalid query types"""
    result = duckduckgo_web_search("Testing web search", invalid_query)
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid query" in result_dict["error"]["message"]


@pytest.mark.parametrize(
    "invalid_max_results",
    [
        -1,
        -100,
        0,
        "10",
        10.5,
        None,
        [],
    ],
)
def test_web_search_invalid_max_results_types(invalid_max_results):
    """Test web search with various invalid max_results types"""
    result = duckduckgo_web_search(
        "Testing web search", "test query", max_results=invalid_max_results
    )
    result_dict = json.loads(result)

    assert result_dict["tool"] == "duckduckgo_web_search"
    assert result_dict["status"] == "error"
    assert "Invalid max_results" in result_dict["error"]["message"]
