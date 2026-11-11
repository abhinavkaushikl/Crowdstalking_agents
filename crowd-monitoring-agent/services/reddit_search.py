"""
Reddit's official API, OAuth "client_credentials" (app-only, no user login
needed since we only read public posts). Free tier is fine at low volume.
"""
import os
import time

import requests

from utils.config_loader import get as config_get

DEFAULT_LIMIT = config_get("search.reddit_default_limit", 15)
SEARCH_WINDOW = config_get("search.reddit_search_window", "year")

_token_cache = {"token": None, "expires_at": 0}


def _get_token():
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT") or "crowd-monitoring-agent/0.1"
    if not client_id or not client_secret:
        raise RuntimeError("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set")

    res = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": user_agent},
        timeout=10
    )
    if res.status_code != 200:
        raise RuntimeError(f"Reddit token request failed: HTTP {res.status_code}")
    data = res.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data["expires_in"] - 60
    return _token_cache["token"]


def search_reddit(query, limit=None):
    try:
        token = _get_token()
    except Exception as e:
        return {"error": str(e), "results": []}

    user_agent = os.environ.get("REDDIT_USER_AGENT") or "crowd-monitoring-agent/0.1"
    try:
        res = requests.get(
            "https://oauth.reddit.com/search",
            params={"q": query, "sort": "relevance", "t": SEARCH_WINDOW, "limit": limit or DEFAULT_LIMIT},
            headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent},
            timeout=10
        )
        if res.status_code != 200:
            return {"error": f"Reddit search failed: HTTP {res.status_code}", "results": []}
        data = res.json()
        posts = []
        for child in data.get("data", {}).get("children", []):
            d = child["data"]
            posts.append({
                "title": d.get("title"),
                "snippet": (d.get("selftext") or "")[:400],
                "subreddit": d.get("subreddit_name_prefixed"),
                "score": d.get("score"),
                "permalink": f"https://reddit.com{d.get('permalink')}"
            })
        return {"result_count": len(posts), "results": posts}
    except Exception as e:
        return {"error": str(e), "results": []}
