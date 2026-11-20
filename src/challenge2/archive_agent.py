from __future__ import annotations

import csv
import json
from pathlib import Path


MOCK_ARCHIVE = [
    {"title": "Saftiger Gewürzkuchen", "published": "2025-11-09", "ingredients": ["mehl", "gewürze", "sirup"]},
    {"title": "Vanillekipferl klassisch", "published": "2024-12-14", "ingredients": ["mehl", "butter", "vanille"]},
    {"title": "Herbstlicher Rosenkohl-Auflauf", "published": "2025-09-22", "ingredients": ["rosenkohl", "käse", "rahm"]},
]


class ArchiveAgent:
    def __init__(self, archive_path: Path | None = None):
        self.archive_path = archive_path
        self.archive_available = False
        self.recipes = []
        if archive_path is not None and archive_path.exists():
            self.recipes = self._load(archive_path)
            self.archive_available = bool(self.recipes)

    @staticmethod
    def _load(path: Path) -> list[dict]:
        if path.suffix.casefold() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("recipes", [])
        if path.suffix.casefold() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
        return []

    def check(self, topic: str) -> dict:
        if not self.archive_available:
            return {
                "status": "archive_unavailable",
                "available": False,
                "match_status": "archive_unavailable",
                "similar_recipes": [],
                "most_recent_comparable_publication": None,
                "recurring_ingredients": [],
                "recurring_methods": [],
                "repetition_risk": "unknown",
                "content_gap": "Archive export unavailable; content gap cannot be verified.",
                "assumption": (
                    "The supplied archive export contains topic mappings, not a complete "
                    "recipe export. No claim is made about archive matches."
                ),
            }

        keywords = topic.lower().split()
        matches = [
            recipe
            for recipe in self.recipes
            if any(
                keyword in " ".join(
                    recipe.get("ingredients", [])
                    if isinstance(recipe.get("ingredients", []), list)
                    else str(recipe.get("ingredients", "")).split(",")
                ).lower()
                for keyword in keywords
            )
            or keyword_match(topic, recipe["title"])
        ]
        if not matches:
            risk = "low"
            gap = "No close archived match was found."
            match_status = "no_match_found"
        elif len(matches) >= 2:
            risk = "high"
            gap = "Strong overlap exists; a clearly differentiated format is required."
            match_status = "matches_found"
        else:
            risk = "medium"
            gap = "A nearby recipe exists, but the format or seasonal angle can be differentiated."
            match_status = "matches_found"

        dates = [
            recipe.get("published") or recipe.get("publication_date")
            for recipe in matches
        ]
        dates = [value for value in dates if value]
        recurring_ingredients = sorted({
            ingredient.lower()
            for recipe in matches
            for ingredient in (
                recipe.get("ingredients", [])
                if isinstance(recipe.get("ingredients", []), list)
                else str(recipe.get("ingredients", "")).split(",")
            )
        })
        recurring_methods = sorted({
            str(recipe.get("method"))
            for recipe in matches
            if recipe.get("method")
        })
        return {
            "status": "available",
            "available": True,
            "match_status": match_status,
            "similar_recipes": matches,
            "most_recent_comparable_publication": max(dates) if dates else None,
            "recurring_ingredients": recurring_ingredients,
            "recurring_methods": recurring_methods,
            "repetition_risk": risk,
            "content_gap": gap,
            "assumption": "Matched against the supplied archive export.",
        }


def keyword_match(topic: str, title: str) -> bool:
    stop_words = {"and", "or", "der", "die", "das", "food", "vegetable"}
    terms = {
        term
        for term in topic.lower().replace("(", " ").replace(")", " ").split()
        if term not in stop_words
    }
    return bool(terms.intersection(title.lower().split()) - stop_words)
