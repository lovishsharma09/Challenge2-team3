from __future__ import annotations

from typing import Any

import requests

from .config import BRAVE_SEARCH_ENDPOINT, get_brave_api_key


class BraveSearchError(RuntimeError):
    pass


def brave_web_search(query: str, count: int = 10) -> list[dict[str, Any]]:
    api_key = get_brave_api_key()
    if not api_key:
        raise BraveSearchError(
            "BRAVE_SEARCH_API_KEY is missing. Set it in src/challenge2/config.py."
        )

    try:
        response = requests.get(
            BRAVE_SEARCH_ENDPOINT,
            headers={
                "Accept": "application/json",
                "x-subscription-token": api_key,
            },
            params={
                "q": query,
                "country": "DE",
                "search_lang": "de",
                "count": min(max(count, 1), 20),
                "freshness": "pm",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise BraveSearchError(f"Brave Search request failed: {exc}") from exc
    if not response.ok:
        raise BraveSearchError(
            f"Brave Search returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    return payload.get("web", {}).get("results", [])

