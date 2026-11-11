"""
Registers the web/Reddit search tools the Social Media Hunter agent can call,
backed by services/google_search.py and services/reddit_search.py.

Kept in its own registry (search_registry) rather than one global registry,
so a future dispatch/tip agent's tools are never accidentally offered to the
Social Media Hunter, and vice versa.

Mock fallback: if a provider's real API keys aren't configured (or
search.force_mock is set in config/settings.yaml), that specific tool routes
to services/mock_search.py instead of returning an empty/error result - so
the Social Media Hunter's actual Groq reasoning can still be exercised
end-to-end against realistic synthetic content. Every mock result carries
"simulated": True so it's never confused with a real search result.
"""
import os
from typing import Optional

from services import mock_search
from services.google_search import web_search as real_web_search
from services.reddit_search import search_reddit as real_search_reddit
from tools.registry import ToolRegistry
from utils.config_loader import get as config_get

FORCE_MOCK = config_get("search.force_mock", False)

search_registry = ToolRegistry()


def _google_keys_present():
    return bool(os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX"))


def _reddit_keys_present():
    return bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))


@search_registry.tool(
    name="web_search",
    description="Search the live web via Google for news/info about a specific area or situation.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}, "num_results": {"type": "number"}},
        "required": ["query"],
    },
)
def _web_search(query: str, num_results: Optional[int] = None) -> dict:
    if FORCE_MOCK or not _google_keys_present():
        return mock_search.web_search(query, num_results)
    return real_web_search(query, num_results)


@search_registry.tool(
    name="reddit_search",
    description="Search Reddit for recent posts/discussion about a specific area or situation.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "number"}},
        "required": ["query"],
    },
)
def _reddit_search(query: str, limit: Optional[int] = None) -> dict:
    if FORCE_MOCK or not _reddit_keys_present():
        return mock_search.search_reddit(query, limit)
    return real_search_reddit(query, limit)
