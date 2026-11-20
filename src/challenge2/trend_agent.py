from __future__ import annotations

import csv
from datetime import date
import re
from pathlib import Path

from .brave_search import BraveSearchError, brave_web_search


class TrendAgent:
    def __init__(self, google_trends_dir: Path):
        self.google_trends_dir = google_trends_dir

    def load_rising_topics(self) -> list[dict[str, str]]:
        path = self.google_trends_dir / (
            "searched_with_rising-searches_topics_DE_20261018-1818_20261118-1818.csv"
        )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def score_topic(self, topic: str, raw_score: str, explanation: str = "") -> dict:
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            score = 0
        normalized = min(100, max(0, score))
        return {
            "topic": topic,
            "trend_score": normalized,
            "why_relevant": explanation
            or f"{topic} shows rising search interest in the supplied Google Trends signal.",
            "sources": ["Google Trends supplied data"],
        }

    def propose_from_local_signals(self, limit: int = 8) -> list[dict]:
        proposals: list[dict] = []
        period_start = "2026-10-18"
        period_end = "2026-11-18"
        for row in self.load_rising_topics()[:limit]:
            interest = row.get("search interest", "0")
            try:
                interest_score = int(interest)
            except ValueError:
                interest_score = 0
            score = min(100, interest_score * 2)
            proposals.append(
                self.score_topic(row.get("topic", ""), str(score), "")
            )
            proposals[-1]["trend_points"] = [{
                "date": period_end,
                "value": interest_score,
                "source": "Google Trends Rising Topics",
                "period_start": period_start,
                "period_end": period_end,
            }]
        return proposals

    def enrich_with_brave(self, topic: dict) -> dict:
        topic_name = topic["topic"]
        try:
            results = brave_web_search(topic_name, count=5)
        except BraveSearchError:
            return topic
        if not results:
            return topic

        sources = topic.setdefault("sources", [])
        sources.extend(
            result["url"]
            for result in results
            if result.get("url") and result["url"] not in sources
        )
        topic["why_relevant"] = (
            f"{topic_name} shows rising search interest and is supported by "
            f"{len(results)} recent independent web sources."
        )
        topic["brave_results"] = [
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "description": result.get("description"),
            }
            for result in results
        ]
        if "trend_points" not in topic:
            topic["trend_points"] = []
        topic["trend_points"].append({
            "date": date.today().isoformat(),
            "value": len(results),
            "source": "Brave Web Search",
            "query": topic_name,
        })
        return topic

