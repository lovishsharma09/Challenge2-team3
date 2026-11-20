from __future__ import annotations

from typing import Iterable


MOCK_ARCHIVE = [
    {"title": "Saftiger Gewürzkuchen", "published": "2025-11-09", "ingredients": ["mehl", "gewürze", "sirup"]},
    {"title": "Vanillekipferl klassisch", "published": "2024-12-14", "ingredients": ["mehl", "butter", "vanille"]},
    {"title": "Herbstlicher Rosenkohl-Auflauf", "published": "2025-09-22", "ingredients": ["rosenkohl", "käse", "rahm"]},
]


class ArchiveAgent:
    def check(self, topic: str) -> dict:
        archive_available = False
        keywords = topic.lower().split()
        matches = [
            recipe
            for recipe in MOCK_ARCHIVE
            if any(keyword in " ".join(recipe["ingredients"]).lower() for keyword in keywords)
            or keyword_match(topic, recipe["title"])
        ]
        if not matches:
            risk = "low"
            gap = "No close archive match can be established from the supplied fixture."
        elif len(matches) >= 2:
            risk = "high"
            gap = "Strong overlap exists; a clearly differentiated format is required."
        else:
            risk = "medium"
            gap = "A nearby recipe exists, but the format or seasonal angle can be differentiated."
        return {
            "status": "mock_fixture",
            "available": archive_available,
            "match_status": "no_match_found" if not matches else "matches_found",
            "similar_recipes": matches,
            "repetition_risk": risk,
            "content_gap": gap,
            "assumption": (
                "The archive export is unavailable; the mock fixture is illustrative only."
                if archive_available is False
                else "Matched against the supplied archive export."
            ),
        }


def keyword_match(topic: str, title: str) -> bool:
    stop_words = {"and", "or", "der", "die", "das", "food", "vegetable"}
    terms = {
        term
        for term in topic.lower().replace("(", " ").replace(")", " ").split()
        if term not in stop_words
    }
    return bool(terms.intersection(title.lower().split()) - stop_words)
