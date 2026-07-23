"""
IMDB tool functions for movie and TV series information retrieval.

This module provides tool functions that wrap the imdbinfo package
for use with the Aria agent.

Each function returns a JSON string with explicitly documented fields.
The imdbinfo package returns Pydantic models (MovieBriefInfo, PersonDetail,
MovieDetail, BulkedEpisode) or plain dicts (reviews, trivia). We extract
a curated subset of fields from each model to keep responses lean and
self-documenting.
"""

import inspect
from functools import wraps

from imdbinfo import TitleType as ImdbTitleType
from imdbinfo import (
    get_all_episodes,
    get_filmography,
    get_movie,
    get_name,
    get_reviews,
    get_trivia,
    search_title,
)
from loguru import logger

from aria.tools import (
    Reason,
    get_function_name,
    tool_error_response,
    tool_success_response,
)
from aria.tools.decorators import log_tool_call
from aria.tools.imdb.constants import (
    ERROR_EMPTY_IMDB_ID,
    ERROR_EMPTY_QUERY,
    ERROR_EPISODES_NOT_FOUND,
    ERROR_FILMOGRAPHY_NOT_FOUND,
    ERROR_INVALID_TITLE_TYPE,
    ERROR_MOVIE_NOT_FOUND,
    ERROR_NETWORK,
    ERROR_NO_RESULTS,
    ERROR_PERSON_NOT_FOUND,
    ERROR_RATE_LIMIT,
    ERROR_REVIEWS_NOT_FOUND,
    ERROR_TIMEOUT,
    ERROR_TRIVIA_NOT_FOUND,
    ERROR_UNKNOWN,
    VALID_TITLE_TYPES,
)


def _get_title_type(title_type: str | None) -> ImdbTitleType | None:
    """
    Convert user-friendly title type string to ImdbTitleType enum.

    Args:
        title_type: User-friendly title type string (e.g., 'movie', 'series')

    Returns:
        ImdbTitleType enum value or None if no filter specified

    Raises:
        ValueError: If title_type is not a valid type
    """
    if title_type is None:
        return None

    title_type_lower = title_type.lower().strip()
    if title_type_lower not in VALID_TITLE_TYPES:
        valid_types = ", ".join(sorted(VALID_TITLE_TYPES.keys()))
        raise ValueError(
            ERROR_INVALID_TITLE_TYPE.format(value=title_type, valid_types=valid_types)
        )

    enum_name = VALID_TITLE_TYPES[title_type_lower]
    return getattr(ImdbTitleType, enum_name)


def _classify_error(error: Exception) -> str:
    """
    Classify an exception into a user-friendly error message.

    Args:
        error: The exception that occurred

    Returns:
        A clean, agent-friendly error message string
    """
    error_str = str(error).lower()

    if any(
        term in error_str
        for term in ["connection", "network", "dns", "resolve", "unreachable"]
    ):
        return ERROR_NETWORK

    if any(term in error_str for term in ["timeout", "timed out"]):
        return ERROR_TIMEOUT

    if any(term in error_str for term in ["rate limit", "429", "too many"]):
        return ERROR_RATE_LIMIT

    return ERROR_UNKNOWN.format(error=str(error))


def _imdb_tool(error_not_found_msg_template: str, *, id_param: str = "imdb_id"):
    """Decorator for IMDB tool functions.

    Handles ID validation and standardized error handling.

    Args:
        error_not_found_msg_template: Message template for not-found cases.
        id_param: Name of the ID parameter to validate and normalize.
    """

    def _format_not_found_msg(id_value: str) -> str:
        return error_not_found_msg_template.format(**{id_param: id_value})

    def decorator(func):
        signature = inspect.signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs) -> str:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()

            reason = str(bound.arguments.get("reason", "unknown"))
            raw_id = bound.arguments.get(id_param)

            if not isinstance(raw_id, str) or not raw_id.strip():
                return tool_error_response(
                    get_function_name(),
                    reason,
                    ValueError(ERROR_EMPTY_IMDB_ID),
                )

            normalized_id = raw_id.strip()
            bound.arguments[id_param] = normalized_id

            try:
                return func(*bound.args, **bound.kwargs)
            except ValueError as e:
                expected_not_found = _format_not_found_msg(normalized_id)
                if "not found" in str(e).lower() or expected_not_found in str(e):
                    return tool_error_response(
                        get_function_name(),
                        reason,
                        ValueError(expected_not_found),
                    )
                logger.error(f"{get_function_name()} validation error: {e}")
                return tool_error_response(get_function_name(), reason, e)
            except Exception as e:
                logger.error(f"{func.__name__} failed: {e}")
                return tool_error_response(
                    get_function_name(),
                    reason,
                    RuntimeError(_classify_error(e)),
                )

        return wrapper

    return decorator


def _no_results(reason: str, query: str) -> str:
    return tool_error_response(
        get_function_name(),
        reason,
        ValueError(ERROR_NO_RESULTS.format(query=query)),
    )


def _has_results(result) -> bool:
    return bool(result.titles or result.names)


def _serialize_titles(result) -> list[dict]:
    return [
        {
            "imdbId": t.imdbId,
            "title": t.title,
            "year": t.year,
            "kind": t.kind,
            "rating": t.rating,
        }
        for t in (result.titles or [])
    ]


def _serialize_names(result) -> list[dict]:
    return [
        {
            "imdbId": n.imdbId,
            "name": n.name,
            "job": n.job,
        }
        for n in (result.names or [])
    ]


@log_tool_call
def search_imdb_titles(reason: str, query: str, title_type: str | None = None) -> str:
    """Search IMDb titles or people and get IDs for follow-up lookups.

    Use this first when you do not already have an IMDb ID.

    Args:
        reason: Required. Brief explanation of why you are searching IMDb.
        query: Title or person name to search for.
        title_type: Optional title filter.

    Returns:
        JSON with matching titles and people.
    """
    logger.info(f"search_imdb_titles called with query='{query}'")

    if not query or not query.strip():
        return tool_error_response(
            get_function_name(), reason, ValueError(ERROR_EMPTY_QUERY)
        )

    try:
        imdb_title_type = _get_title_type(title_type)
        logger.debug(f"Title type filter: {imdb_title_type}")

        result = search_title(query.strip(), title_type=imdb_title_type)

        if result is None or not _has_results(result):
            return _no_results(reason, query)

        titles = _serialize_titles(result)
        names = _serialize_names(result)
        response = {"titles": titles, "names": names}

        logger.info(f"Found {len(titles)} titles, {len(names)} names")
        return tool_success_response(get_function_name(), reason, response)

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return tool_error_response(get_function_name(), reason, e)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return tool_error_response(
            get_function_name(), reason, RuntimeError(_classify_error(e))
        )


def _person_summary(person) -> dict:
    return {"imdbId": person.imdbId, "name": person.name}


def _credits_from_categories(movie, key: str) -> list[dict]:
    items = (movie.categories or {}).get(key, [])
    return [_person_summary(p) for p in items]


def _directors(movie) -> list[dict]:
    if movie.directors:
        return [_person_summary(d) for d in movie.directors]
    return _credits_from_categories(movie, "director")


def _cast(movie) -> list[dict]:
    items = (movie.categories or {}).get("cast", [])
    return [
        {
            "imdbId": c.imdbId,
            "name": c.name,
            "characters": getattr(c, "characters", []),
        }
        for c in items
    ]


def _awards_payload(movie) -> dict | None:
    if not movie.awards:
        return None
    return {
        "wins": movie.awards.wins,
        "nominations": movie.awards.nominations,
        "prestigious_award": movie.awards.prestigious_award,
    }


@log_tool_call
@_imdb_tool(ERROR_MOVIE_NOT_FOUND.format(imdb_id="{imdb_id}"))
def get_movie_details(reason: Reason, imdb_id: str) -> str:
    """Get detailed data for a movie or TV series by IMDb ID.

    Use this after ``search_imdb_titles`` when the user wants full title details.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        imdb_id: IMDb title ID.

    Returns:
        JSON with core title metadata, credits, plot, ratings, and awards.
    """
    logger.info(f"get_movie_details called with imdb_id='{imdb_id}'")

    movie = get_movie(imdb_id)

    if movie is None:
        raise ValueError(ERROR_MOVIE_NOT_FOUND.format(imdb_id=imdb_id))

    result = {
        "imdbId": movie.imdbId,
        "title": movie.title,
        "year": movie.year,
        "kind": movie.kind,
        "duration": movie.duration,
        "rating": movie.rating,
        "votes": movie.votes,
        "metacritic_rating": movie.metacritic_rating,
        "mpaa": movie.mpaa,
        "plot": movie.plot,
        "genres": movie.genres or [],
        "languages_text": movie.languages_text or [],
        "countries": movie.countries or [],
        "directors": _directors(movie),
        "writers": _credits_from_categories(movie, "writer"),
        "producers": _credits_from_categories(movie, "producer"),
        "cast": _cast(movie),
        "stars": [_person_summary(s) for s in (movie.stars or [])],
        "release_date": movie.release_date,
        "cover_url": movie.cover_url,
        "worldwide_gross": movie.worldwide_gross,
        "production_budget": movie.production_budget,
        "awards": _awards_payload(movie),
        "trailers": movie.trailers or [],
    }

    logger.info(f"Retrieved details for '{movie.title}' ({movie.year})")
    return tool_success_response(get_function_name(), reason, result)


@log_tool_call
@_imdb_tool(
    ERROR_PERSON_NOT_FOUND.format(person_id="{person_id}"),
    id_param="person_id",
)
def get_person_details(reason: Reason, person_id: str) -> str:
    """Get details for an actor, director, or other IMDb person.

    Use this after ``search_imdb_titles`` when you have a person ID.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        person_id: IMDb person ID.

    Returns:
        JSON with biography, dates, known-for titles, and profession data.
    """
    logger.info(f"get_person_details called with person_id='{person_id}'")

    person = get_name(person_id)

    if person is None:
        raise ValueError(ERROR_PERSON_NOT_FOUND.format(person_id=person_id))

    result = {
        "imdbId": person.imdbId,
        "name": person.name,
        "bio": person.bio,
        "image_url": person.image_url,
        "birth_date": person.birth_date,
        "birth_place": person.birth_place,
        "death_date": person.death_date,
        "death_place": person.death_place,
        "knownfor": person.knownfor or [],
        "primary_profession": person.primary_profession or [],
        "height": person.height,
    }

    logger.info(f"Retrieved details for person '{person.name}'")
    return tool_success_response(get_function_name(), reason, result)


@log_tool_call
@_imdb_tool(
    ERROR_FILMOGRAPHY_NOT_FOUND.format(person_id="{person_id}"),
    id_param="person_id",
)
def get_person_filmography(reason: Reason, person_id: str) -> str:
    """Get the filmography for an IMDb person by ID.

    Use this after ``search_imdb_titles`` for role-based credits.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        person_id: IMDb person ID.

    Returns:
        JSON with credits grouped by role.
    """
    logger.info(f"get_person_filmography called with person_id='{person_id}'")

    filmography = get_filmography(person_id)

    if not filmography:
        raise ValueError(ERROR_FILMOGRAPHY_NOT_FOUND.format(person_id=person_id))

    serialized = {}
    if isinstance(filmography, dict):
        for category, credits in filmography.items():
            serialized[category] = [
                {
                    "imdbId": c.imdbId,
                    "title": c.title,
                    "year": c.year,
                    "kind": c.kind,
                    "rating": c.rating,
                }
                for c in credits
            ]

    result = {
        "person_id": person_id,
        "filmography": serialized,
    }

    logger.info(f"Retrieved filmography for person_id='{person_id}'")
    return tool_success_response(get_function_name(), reason, result)


@log_tool_call
@_imdb_tool(ERROR_EPISODES_NOT_FOUND.format(imdb_id="{imdb_id}"))
def get_all_series_episodes(reason: Reason, imdb_id: str) -> str:
    """Get all episodes for a TV series by IMDb ID.

    Use this after ``search_imdb_titles`` for series episode lists.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        imdb_id: IMDb series ID.

    Returns:
        JSON with episode metadata in chronological order.
    """
    logger.info(f"get_all_series_episodes called with imdb_id='{imdb_id}'")

    episodes = get_all_episodes(imdb_id)

    if not episodes:
        raise ValueError(ERROR_EPISODES_NOT_FOUND.format(imdb_id=imdb_id))

    serialized_episodes = [
        {
            "imdbId": ep.imdbId,
            "title": ep.title,
            "year": ep.year,
            "rating": ep.rating,
            "votes": ep.votes,
            "plot": ep.plot,
            "release_date": ep.release_date,
            "duration": ep.duration,
            "genres": ep.genres or [],
        }
        for ep in episodes
    ]

    result = {
        "series_id": imdb_id,
        "episode_count": len(episodes),
        "episodes": serialized_episodes,
    }

    logger.info(f"Retrieved {len(episodes)} episodes for series '{imdb_id}'")
    return tool_success_response(get_function_name(), reason, result)


@log_tool_call
@_imdb_tool(ERROR_REVIEWS_NOT_FOUND.format(imdb_id="{imdb_id}"))
def get_movie_reviews(reason: Reason, imdb_id: str) -> str:
    """Get user reviews for a movie or TV series by IMDb ID.

    Use this after ``search_imdb_titles`` for audience-opinion questions.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        imdb_id: IMDb title ID.

    Returns:
        JSON with review metadata and text.
    """
    logger.info(f"get_movie_reviews called with imdb_id='{imdb_id}'")

    reviews = get_reviews(imdb_id)

    if not reviews:
        raise ValueError(ERROR_REVIEWS_NOT_FOUND.format(imdb_id=imdb_id))

    result = {
        "imdb_id": imdb_id,
        "review_count": len(reviews),
        "reviews": reviews if isinstance(reviews, list) else [],
    }

    logger.info(f"Retrieved {len(reviews)} reviews for '{imdb_id}'")
    return tool_success_response(get_function_name(), reason, result)


@log_tool_call
@_imdb_tool(ERROR_TRIVIA_NOT_FOUND.format(imdb_id="{imdb_id}"))
def get_movie_trivia(reason: Reason, imdb_id: str) -> str:
    """Get trivia for a movie or TV series by IMDb ID.

    Use this after ``search_imdb_titles`` for fun-facts or behind-the-scenes queries.

    Args:
        reason: Required. Brief explanation of why you are fetching this data.
        imdb_id: IMDb title ID.

    Returns:
        JSON with trivia entries and related titles.
    """
    logger.info(f"get_movie_trivia called with imdb_id='{imdb_id}'")

    trivia = get_trivia(imdb_id)

    if not trivia:
        raise ValueError(ERROR_TRIVIA_NOT_FOUND.format(imdb_id=imdb_id))

    result = {
        "imdb_id": imdb_id,
        "trivia_count": len(trivia),
        "trivia": trivia if isinstance(trivia, list) else [],
    }

    logger.info(f"Retrieved {len(trivia)} trivia items for '{imdb_id}'")
    return tool_success_response(get_function_name(), reason, result)
