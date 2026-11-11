"""
Google Custom Search JSON API - 100 free queries/day, no billing account.
Degrades gracefully (returns {error, results: []}) when GOOGLE_CSE_API_KEY/CX
aren't set yet, or the daily free quota is exhausted - never raises out to
the agent loop, which would otherwise kill the whole pipeline over one
missing key.
"""
import os
import time

import requests

from utils.config_loader import get as config_get

_cache = {}
CACHE_TTL_SECONDS = config_get("search.google_cache_ttl_seconds", 86400)


def web_search(query, num_results=None):
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_CX")
    if not api_key or not cx:
        return {"error": "GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX not set", "results": []}

    n = min(int(num_results or 5), 10)
    cache_key = f"{query}:{n}"
    entry = _cache.get(cache_key)
    if entry and time.time() < entry["expires"]:
        return entry["value"]

    try:
        res = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": n},
            timeout=10
        )
        data = res.json()
        if res.status_code != 200:
            return {"error": data.get("error", {}).get("message", f"HTTP {res.status_code}"), "results": []}
        results = [{"title": it.get("title"), "link": it.get("link"), "snippet": it.get("snippet")} for it in data.get("items", [])]
        out = {"result_count": len(results), "results": results}
        _cache[cache_key] = {"value": out, "expires": time.time() + CACHE_TTL_SECONDS}
        return out
    except Exception as e:
        return {"error": str(e), "results": []}
