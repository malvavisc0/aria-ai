"""Tests for IMDB tool functions.

This module tests the IMDB tool functions with mocked API responses
to avoid making real API calls during testing.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from aria.tools.imdb.constants import (
    ERROR_EMPTY_IMDB_ID,
    ERROR_EMPTY_QUERY,
    ERROR_INVALID_TITLE_TYPE,
    ERROR_NETWORK,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
)
from aria.tools.imdb.functions import (
    _classify_error,
    _get_title_type,
    get_all_series_episodes,
    get_movie_details,
    get_movie_reviews,
    get_movie_trivia,
    get_person_details,
    get_person_filmography,
    search_imdb_titles,
)


def _response_data(raw: str) -> dict:
    return json.loads(raw)["data"]


def _response_error(raw: str) -> str:
    return json.loads(raw)["error"]["message"]


class TestGetTitleType:
    """Tests for _get_title_type helper function."""

    def test_none_returns_none(self):
        """Test that None input returns None."""
        result = _get_title_type(None)
        assert result is None

    def test_movie_type(self):
        """Test 'movie' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("movie")
        assert result == TitleType.Movies

    def test_movies_alias(self):
        """Test 'movies' alias returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("movies")
        assert result == TitleType.Movies

    def test_series_type(self):
        """Test 'series' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("series")
        assert result == TitleType.Series

    def test_tv_alias(self):
        """Test 'tv' alias returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("tv")
        assert result == TitleType.Series

    def test_episode_type(self):
        """Test 'episode' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("episode")
        assert result == TitleType.Episodes

    def test_short_type(self):
        """Test 'short' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("short")
        assert result == TitleType.Shorts

    def test_tv_movie_type(self):
        """Test 'tv_movie' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("tv_movie")
        assert result == TitleType.TvMovie

    def test_video_type(self):
        """Test 'video' returns correct enum."""
        from imdbinfo import TitleType

        result = _get_title_type("video")
        assert result == TitleType.Video

    def test_case_insensitive(self):
        """Test that type matching is case-insensitive."""
        from imdbinfo import TitleType

        result = _get_title_type("MOVIE")
        assert result == TitleType.Movies

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from input."""
        from imdbinfo import TitleType

        result = _get_title_type("  movie  ")
        assert result == TitleType.Movies

    def test_invalid_type_raises_error(self):
        """Test that invalid type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            _get_title_type("invalid_type")
        assert ERROR_INVALID_TITLE_TYPE.split("{")[0] in str(exc_info.value)


class TestClassifyError:
    """Tests for _classify_error helper function."""

    def test_connection_error(self):
        """Test classification of connection errors."""
        error = Exception("Connection refused")
        result = _classify_error(error)
        assert result == ERROR_NETWORK

    def test_network_error(self):
        """Test classification of network errors."""
        error = Exception("Network unreachable")
        result = _classify_error(error)
        assert result == ERROR_NETWORK

    def test_dns_error(self):
        """Test classification of DNS errors."""
        error = Exception("DNS resolve failed")
        result = _classify_error(error)
        assert result == ERROR_NETWORK

    def test_timeout_error(self):
        """Test classification of timeout errors."""
        error = Exception("Request timed out")
        result = _classify_error(error)
        assert result == ERROR_TIMEOUT

    def test_rate_limit_error(self):
        """Test classification of rate limit errors."""
        error = Exception("Rate limit exceeded (429)")
        result = _classify_error(error)
        assert result == ERROR_RATE_LIMIT

    def test_unknown_error(self):
        """Test classification of unknown errors."""
        error = Exception("Something unexpected")
        result = _classify_error(error)
        assert "Something unexpected" in result


class TestSearchImdbTitles:
    """Tests for search_imdb_titles function."""

    @patch("aria.tools.imdb.functions.search_title")
    def test_search_success(self, mock_search):
        """Test successful title search."""
        mock_result = MagicMock()
        mock_title = MagicMock()
        mock_title.imdbId = "tt0133093"
        mock_title.title = "The Matrix"
        mock_title.year = 1999
        mock_title.kind = "movie"
        mock_title.rating = 8.7
        mock_result.titles = [mock_title]
        mock_result.names = []
        mock_search.return_value = mock_result

        result = _response_data(search_imdb_titles("Search for Matrix", "Matrix"))
        assert "titles" in result
        assert len(result["titles"]) == 1
        assert result["titles"][0]["imdbId"] == "tt0133093"
        assert result["titles"][0]["title"] == "The Matrix"

    @patch("aria.tools.imdb.functions.search_title")
    def test_search_with_names(self, mock_search):
        """Test search returning both titles and names."""
        mock_result = MagicMock()
        mock_title = MagicMock()
        mock_title.imdbId = "tt0133093"
        mock_title.title = "The Matrix"
        mock_title.year = 1999
        mock_title.kind = "movie"
        mock_title.rating = 8.7
        mock_name = MagicMock()
        mock_name.imdbId = "nm0000206"
        mock_name.name = "Keanu Reeves"
        mock_name.job = "actor"
        mock_result.titles = [mock_title]
        mock_result.names = [mock_name]
        mock_search.return_value = mock_result

        result = _response_data(search_imdb_titles("Search", "Matrix"))
        assert len(result["titles"]) == 1
        assert len(result["names"]) == 1
        assert result["names"][0]["name"] == "Keanu Reeves"

    def test_search_empty_query(self):
        """Test search with empty query returns error."""
        err = _response_error(search_imdb_titles("Search", ""))
        assert err == ERROR_EMPTY_QUERY

    def test_search_whitespace_query(self):
        """Test search with whitespace-only query returns error."""
        err = _response_error(search_imdb_titles("Search", "   "))
        assert err == ERROR_EMPTY_QUERY

    @patch("aria.tools.imdb.functions.search_title")
    def test_search_no_results(self, mock_search):
        """Test search with no results."""
        mock_result = MagicMock()
        mock_result.titles = []
        mock_result.names = []
        mock_search.return_value = mock_result

        err = _response_error(search_imdb_titles("Search", "nonexistent"))
        assert "No results found" in err

    @patch("aria.tools.imdb.functions.search_title")
    def test_search_with_title_type_filter(self, mock_search):
        """Test search with title type filter."""
        from imdbinfo import TitleType

        mock_result = MagicMock()
        mock_result.titles = []
        mock_result.names = []
        mock_search.return_value = mock_result

        search_imdb_titles("Search", "Matrix", title_type="movie")
        mock_search.assert_called_once_with("Matrix", title_type=TitleType.Movies)

    @patch("aria.tools.imdb.functions.search_title")
    def test_search_exception(self, mock_search):
        """Test search handling exceptions."""
        mock_search.side_effect = Exception("Network error")
        err = _response_error(search_imdb_titles("Search", "Matrix"))
        assert err


class TestGetMovieDetails:
    """Tests for get_movie_details function."""

    @patch("aria.tools.imdb.functions.get_movie")
    def test_get_details_success(self, mock_get_movie):
        """Test successful movie details retrieval."""
        mock_movie = MagicMock()
        mock_movie.imdbId = "tt0133093"
        mock_movie.title = "The Matrix"
        mock_movie.year = 1999
        mock_movie.kind = "movie"
        mock_movie.duration = 136.0
        mock_movie.rating = 8.7
        mock_movie.votes = 2230088
        mock_movie.metacritic_rating = 73
        mock_movie.mpaa = "R"
        mock_movie.plot = "A computer hacker learns about the Matrix"
        mock_movie.genres = ["Action", "Sci-Fi"]
        mock_movie.languages_text = ["English"]
        mock_movie.countries = ["United States", "Australia"]
        mock_movie.directors = []
        mock_movie.stars = []
        mock_movie.categories = {}
        mock_movie.release_date = "1999-03-31"
        mock_movie.cover_url = "https://example.com/cover.jpg"
        mock_movie.worldwide_gross = "463517383 USD"
        mock_movie.production_budget = "63000000 USD"
        mock_movie.awards = MagicMock()
        mock_movie.awards.wins = 42
        mock_movie.awards.nominations = 52
        mock_movie.awards.prestigious_award = None
        mock_get_movie.return_value = mock_movie

        result = _response_data(get_movie_details("Get details", "tt0133093"))
        assert result["imdbId"] == "tt0133093"
        assert result["title"] == "The Matrix"
        assert result["year"] == 1999
        assert result["awards"]["wins"] == 42
        assert result["writers"] == []
        assert result["producers"] == []
        assert result["cast"] == []

    @patch("aria.tools.imdb.functions.get_movie")
    def test_get_details_with_writers_and_cast(self, mock_get_movie):
        """Test details with writers, producers, and cast from categories."""
        mock_movie = MagicMock()
        mock_movie.imdbId = "tt0133093"
        mock_movie.title = "The Matrix"
        mock_movie.year = 1999
        mock_movie.kind = "movie"
        mock_movie.duration = 136.0
        mock_movie.rating = 8.7
        mock_movie.votes = 2230088
        mock_movie.metacritic_rating = 73
        mock_movie.mpaa = "R"
        mock_movie.plot = "A computer hacker learns about the Matrix"
        mock_movie.genres = ["Action", "Sci-Fi"]
        mock_movie.languages_text = ["English"]
        mock_movie.countries = ["United States", "Australia"]
        mock_movie.directors = []
        mock_movie.stars = []
        mock_movie.release_date = "1999-03-31"
        mock_movie.cover_url = "https://example.com/cover.jpg"
        mock_movie.worldwide_gross = "463517383 USD"
        mock_movie.production_budget = "63000000 USD"
        mock_movie.awards = None

        # Set up categories with writers, producers, and cast
        mock_writer = MagicMock()
        mock_writer.imdbId = "nm0905152"
        mock_writer.name = "Lilly Wachowski"

        mock_producer = MagicMock()
        mock_producer.imdbId = "nm0905154"
        mock_producer.name = "Joel Silver"

        mock_cast_member = MagicMock()
        mock_cast_member.imdbId = "nm0000206"
        mock_cast_member.name = "Keanu Reeves"
        mock_cast_member.characters = ["Neo"]

        mock_movie.categories = {
            "writer": [mock_writer],
            "producer": [mock_producer],
            "cast": [mock_cast_member],
        }
        mock_get_movie.return_value = mock_movie

        result = _response_data(get_movie_details("Get details", "tt0133093"))
        assert len(result["writers"]) == 1
        assert result["writers"][0]["name"] == "Lilly Wachowski"
        assert result["writers"][0]["imdbId"] == "nm0905152"
        assert len(result["producers"]) == 1
        assert result["producers"][0]["name"] == "Joel Silver"
        assert len(result["cast"]) == 1
        assert result["cast"][0]["name"] == "Keanu Reeves"
        assert result["cast"][0]["characters"] == ["Neo"]

    @patch("aria.tools.imdb.functions.get_movie")
    def test_get_details_director_fallback_from_categories(self, mock_get_movie):
        """Test directors fall back to categories when direct list is empty."""
        mock_movie = MagicMock()
        mock_movie.imdbId = "tt0133093"
        mock_movie.title = "The Matrix"
        mock_movie.year = 1999
        mock_movie.kind = "movie"
        mock_movie.duration = 136.0
        mock_movie.rating = 8.7
        mock_movie.votes = 2230088
        mock_movie.metacritic_rating = 73
        mock_movie.mpaa = "R"
        mock_movie.plot = "A computer hacker learns about the Matrix"
        mock_movie.genres = ["Action", "Sci-Fi"]
        mock_movie.languages_text = ["English"]
        mock_movie.countries = ["United States", "Australia"]
        mock_movie.directors = []  # Empty directors
        mock_movie.stars = []
        mock_movie.release_date = "1999-03-31"
        mock_movie.cover_url = None
        mock_movie.worldwide_gross = None
        mock_movie.production_budget = None
        mock_movie.awards = None

        # Director available in categories as fallback
        mock_cat_director = MagicMock()
        mock_cat_director.imdbId = "nm0905152"
        mock_cat_director.name = "Lana Wachowski"

        mock_movie.categories = {
            "director": [mock_cat_director],
            "writer": [],
            "producer": [],
            "cast": [],
        }
        mock_get_movie.return_value = mock_movie

        result = _response_data(get_movie_details("Get details", "tt0133093"))
        assert len(result["directors"]) == 1
        assert result["directors"][0]["name"] == "Lana Wachowski"

    def test_get_details_empty_id(self):
        """Test get details with empty ID returns error."""
        err = _response_error(get_movie_details("Get details", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_movie")
    def test_get_details_not_found(self, mock_get_movie):
        """Test get details when movie not found."""
        mock_get_movie.return_value = None
        err = _response_error(get_movie_details("Get details", "tt9999999"))
        assert "No movie/series found" in err

    @patch("aria.tools.imdb.functions.get_movie")
    def test_get_details_exception(self, mock_get_movie):
        """Test get details handling exceptions."""
        mock_get_movie.side_effect = Exception("Network error")
        err = _response_error(get_movie_details("Get details", "tt0133093"))
        assert err


class TestGetPersonDetails:
    """Tests for get_person_details function."""

    @patch("aria.tools.imdb.functions.get_name")
    def test_get_person_success(self, mock_get_name):
        """Test successful person details retrieval."""
        mock_person = MagicMock()
        mock_person.imdbId = "nm0000206"
        mock_person.name = "Keanu Reeves"
        mock_person.bio = "Keanu Charles Reeves is a Canadian actor."
        mock_person.image_url = "https://example.com/keanu.jpg"
        mock_person.birth_date = "1964-09-02"
        mock_person.birth_place = "Beirut, Lebanon"
        mock_person.death_date = None
        mock_person.death_place = None
        mock_person.knownfor = ["The Matrix", "John Wick", "Speed"]
        mock_person.primary_profession = ["actor", "producer"]
        mock_person.height = "6' 1\" (1.86 m)"
        mock_get_name.return_value = mock_person

        result = _response_data(get_person_details("Get person", "nm0000206"))
        assert result["imdbId"] == "nm0000206"
        assert result["name"] == "Keanu Reeves"
        assert result["birth_place"] == "Beirut, Lebanon"

    def test_get_person_empty_id(self):
        """Test get person with empty ID returns error."""
        err = _response_error(get_person_details("Get person", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_name")
    def test_get_person_not_found(self, mock_get_name):
        """Test get person when not found."""
        mock_get_name.return_value = None
        err = _response_error(get_person_details("Get person", "nm9999999"))
        assert "No person found" in err


class TestGetPersonFilmography:
    """Tests for get_person_filmography function."""

    @patch("aria.tools.imdb.functions.get_filmography")
    def test_get_filmography_success(self, mock_get_filmography):
        """Test successful filmography retrieval."""
        mock_credit = MagicMock()
        mock_credit.imdbId = "tt15398776"
        mock_credit.title = "Oppenheimer"
        mock_credit.year = 2023
        mock_credit.kind = "movie"
        mock_credit.rating = 8.2

        mock_get_filmography.return_value = {"director": [mock_credit]}

        result = _response_data(get_person_filmography("Get filmography", "nm0634240"))
        assert "filmography" in result
        assert "director" in result["filmography"]
        assert result["filmography"]["director"][0]["title"] == "Oppenheimer"

    def test_get_filmography_empty_id(self):
        """Test get filmography with empty ID returns error."""
        err = _response_error(get_person_filmography("Get filmography", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_filmography")
    def test_get_filmography_not_found(self, mock_get_filmography):
        """Test get filmography when not found."""
        mock_get_filmography.return_value = None
        err = _response_error(get_person_filmography("Get filmography", "nm9999999"))
        assert "No filmography found" in err


class TestGetAllSeriesEpisodes:
    """Tests for get_all_series_episodes function."""

    @patch("aria.tools.imdb.functions.get_all_episodes")
    def test_get_episodes_success(self, mock_get_episodes):
        """Test successful episodes retrieval."""
        mock_episode = MagicMock()
        mock_episode.imdbId = "tt0959621"
        mock_episode.title = "Pilot"
        mock_episode.year = 2008
        mock_episode.rating = 9.0
        mock_episode.votes = 76202
        mock_episode.plot = "Walter White is diagnosed with cancer."
        mock_episode.release_date = "2008-01-20"
        mock_episode.duration = 3480
        mock_episode.genres = ["Crime", "Drama"]

        mock_get_episodes.return_value = [mock_episode]

        result = _response_data(get_all_series_episodes("Get episodes", "tt0903747"))
        assert "episodes" in result
        assert result["episode_count"] == 1
        assert result["episodes"][0]["title"] == "Pilot"

    def test_get_episodes_empty_id(self):
        """Test get episodes with empty ID returns error."""
        err = _response_error(get_all_series_episodes("Get episodes", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_all_episodes")
    def test_get_episodes_not_found(self, mock_get_episodes):
        """Test get episodes when not found."""
        mock_get_episodes.return_value = None
        err = _response_error(get_all_series_episodes("Get episodes", "tt9999999"))
        assert "No episodes found" in err

    @patch("aria.tools.imdb.functions.get_all_episodes")
    def test_get_episodes_empty_list(self, mock_get_episodes):
        """Test get episodes with empty list."""
        mock_get_episodes.return_value = []
        err = _response_error(get_all_series_episodes("Get episodes", "tt9999999"))
        assert "No episodes found" in err


class TestGetMovieReviews:
    """Tests for get_movie_reviews function."""

    @patch("aria.tools.imdb.functions.get_reviews")
    def test_get_reviews_success(self, mock_get_reviews):
        """Test successful reviews retrieval."""
        mock_review = {
            "spoiler": False,
            "summary": "Great movie!",
            "text": "This is an amazing film.",
            "authorRating": 10,
            "upVotes": 100,
            "downVotes": 5,
        }
        mock_get_reviews.return_value = [mock_review]

        result = _response_data(get_movie_reviews("Get reviews", "tt0133093"))
        assert "reviews" in result
        assert result["review_count"] == 1
        assert result["reviews"][0]["summary"] == "Great movie!"

    def test_get_reviews_empty_id(self):
        """Test get reviews with empty ID returns error."""
        err = _response_error(get_movie_reviews("Get reviews", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_reviews")
    def test_get_reviews_not_found(self, mock_get_reviews):
        """Test get reviews when not found."""
        mock_get_reviews.return_value = None
        err = _response_error(get_movie_reviews("Get reviews", "tt9999999"))
        assert "No reviews available" in err


class TestGetMovieTrivia:
    """Tests for get_movie_trivia function."""

    @patch("aria.tools.imdb.functions.get_trivia")
    def test_get_trivia_success(self, mock_get_trivia):
        """Test successful trivia retrieval."""
        mock_trivia = {
            "body": "The movie cost only $8 million to make.",
            "interestScore": {"usersVoted": 1929, "usersInterested": 1903},
        }
        mock_get_trivia.return_value = [mock_trivia]

        result = _response_data(get_movie_trivia("Get trivia", "tt0110912"))
        assert "trivia" in result
        assert result["trivia_count"] == 1
        assert "8 million" in result["trivia"][0]["body"]

    def test_get_trivia_empty_id(self):
        """Test get trivia with empty ID returns error."""
        err = _response_error(get_movie_trivia("Get trivia", ""))
        assert err == ERROR_EMPTY_IMDB_ID

    @patch("aria.tools.imdb.functions.get_trivia")
    def test_get_trivia_not_found(self, mock_get_trivia):
        """Test get trivia when not found."""
        mock_get_trivia.return_value = None
        err = _response_error(get_movie_trivia("Get trivia", "tt9999999"))
        assert "No trivia available" in err


class TestReasonParameter:
    """Tests that reason parameter is accepted and does not affect output."""

    @patch("aria.tools.imdb.functions.get_movie")
    def test_reason_in_get_details(self, mock_get_movie):
        """Test reason parameter in get_movie_details."""
        mock_movie = MagicMock()
        mock_movie.imdbId = "tt0133093"
        mock_movie.title = "Test"
        mock_movie.year = 2000
        mock_movie.kind = "movie"
        mock_movie.duration = 120
        mock_movie.rating = 7.0
        mock_movie.votes = 1000
        mock_movie.metacritic_rating = 70
        mock_movie.mpaa = "R"
        mock_movie.plot = "Test plot"
        mock_movie.genres = []
        mock_movie.languages_text = []
        mock_movie.countries = []
        mock_movie.directors = []
        mock_movie.stars = []
        mock_movie.categories = {}
        mock_movie.release_date = "2000-01-01"
        mock_movie.cover_url = None
        mock_movie.worldwide_gross = None
        mock_movie.production_budget = None
        mock_movie.awards = None
        mock_get_movie.return_value = mock_movie

        result = _response_data(get_movie_details("My reason here", "tt0133093"))
        assert result["imdbId"] == "tt0133093"
