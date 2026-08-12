"""Chainlit starters for the Aria web UI.

This module defines the initial starter messages presented to users
when starting a new chat session.
"""

from __future__ import annotations

import chainlit as cl


def set_starters(user: cl.User | None, language: str | None) -> list[cl.Starter]:
    """Return the list of starter messages for the chat UI."""
    return [
        cl.Starter(
            label="Stock market snapshot",
            message="What's the current price and 5-day trend for NVIDIA (NVDA) stock?",
            icon="/public/icons/chart-line.svg",
        ),
        cl.Starter(
            label="IMDb deep dive",
            message=(
                "Who directed Blade Runner and what else has "
                "Ridley Scott worked on? Compare it to other classic "
                "sci-fi films about artificial intelligence."
            ),
            icon="/public/icons/film.svg",
        ),
        cl.Starter(
            label="Reason through a problem",
            message=(
                "I have $50k to invest and 15 years until retirement. "
                "Reason step by step about a sensible asset allocation, "
                "compare the risk/reward tradeoffs, and give me a concrete "
                "recommendation with the reasoning behind it."
            ),
            icon="/public/icons/lightbulb.svg",
        ),
        cl.Starter(
            label="Research a topic",
            message=(
                "Research the current state of solid-state battery "
                "technology: who the leading players are, the main "
                "technical hurdles, and when commercial adoption is "
                "expected. Summarize your findings with sources."
            ),
            icon="/public/icons/globe.svg",
        ),
    ]
