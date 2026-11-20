from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

import requests


WIKIMEDIA_ENDPOINT = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/"
    "per-article/de.wikipedia.org/all-access/all-agents/"
    "{article}/daily/{start}/{end}"
)


class WikimediaAgent:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Challenge2-Team3/1.0 "
                "(OMMAX Hackathon recipe-trend research prototype)"
            ),
            "Accept": "application/json",
        }

    def article_name(self, topic: str) -> str:
        name = topic.strip()
        for suffix in (" (Food)", " (Vegetable)", " (Fruit)", " (Dish)", " (Meal)"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name.replace("_", " ")

    def fetch_pageviews(
        self,
        topic: str,
        start: date,
        end: date,
    ) -> dict[str, Any]:
        article = self.article_name(topic)
        url = WIKIMEDIA_ENDPOINT.format(
            article=quote(article, safe=""),
            start=start.strftime("%Y%m%d"),
            end=end.strftime("%Y%m%d"),
        )
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as exc:
            return {
                "status": "unavailable",
                "article": article,
                "points": [],
                "error": f"Request failed: {exc}",
            }

        if response.status_code == 404:
            return {
                "status": "no_article_found",
                "article": article,
                "points": [],
                "error": "No German Wikipedia article/pageview series found.",
            }
        if not response.ok:
            return {
                "status": "unavailable",
                "article": article,
                "points": [],
                "error": f"Wikimedia returned HTTP {response.status_code}",
            }

        try:
            items = response.json().get("items", [])
        except ValueError:
            return {
                "status": "unavailable",
                "article": article,
                "points": [],
                "error": "Wikimedia returned a non-JSON response.",
            }
        points = [
            {
                "date": item["timestamp"][:8],
                "value": int(item.get("views", 0)),
                "source": "Wikimedia Pageviews",
                "article": article,
            }
            for item in items
            if item.get("timestamp")
        ]
        if not points:
            return {
                "status": "no_data",
                "article": article,
                "points": [],
                "error": "The API returned no pageview points.",
            }

        return {
            "status": "available",
            "article": article,
            "points": points,
            "score": self.score(points),
            "error": None,
        }

    @staticmethod
    def score(points: list[dict[str, Any]]) -> int:
        if len(points) < 14:
            values = [point["value"] for point in points]
            if not values:
                return 0
            average = sum(values) / len(values)
            return min(100, max(0, round(average / 1000 * 100)))

        values = [point["value"] for point in points]
        split = len(values) // 2
        previous = sum(values[:split]) / split
        recent = sum(values[split:]) / (len(values) - split)
        if previous <= 0:
            return 100 if recent > 0 else 0

        change = ((recent - previous) / previous) * 100
        return min(100, max(0, round(50 + change)))
