from __future__ import annotations

import csv
import json
import hashlib
import math
import re
from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET


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
            self.recipes = self._load_external(archive_path)
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

    @staticmethod
    def _load_external(path: Path) -> list[dict]:
        if path.is_dir():
            return ArchiveAgent._load_xml_directory(path)

        if path.name.casefold() == "auswahl_manifest.json" and path.exists():
            base = path.parent
            manifest = json.loads(path.read_text(encoding="utf-8"))
            entries = manifest.get("rezepte", [])
            recipes = []
            for entry in entries:
                xml_path = base / entry["datei"]
                if entry.get("sha256") and xml_path.exists():
                    digest = hashlib.sha256(xml_path.read_bytes()).hexdigest()
                    if digest != entry["sha256"]:
                        continue
                recipe = ArchiveAgent._load_xml_recipe(xml_path)
                if recipe:
                    recipe["manifest"] = {
                        "hauptkategorie": entry.get("hauptkategorie"),
                        "sha256": entry.get("sha256"),
                        "zutaten_anzahl": entry.get("zutaten_anzahl"),
                        "zubereitungsschritte_anzahl": entry.get("zubereitungsschritte_anzahl"),
                    }
                    recipes.append(recipe)
            return recipes
        return ArchiveAgent._load(path)

    @staticmethod
    def _load_xml_directory(directory: Path) -> list[dict]:
        recipes = []
        for xml_path in sorted(directory.glob("*.xml")):
            recipe = ArchiveAgent._load_xml_recipe(xml_path)
            if recipe:
                recipes.append(recipe)
        return recipes

    @staticmethod
    def _load_xml_recipe(xml_path: Path) -> dict | None:
        try:
            root = ET.parse(xml_path).getroot()
        except (ET.ParseError, OSError):
            return None

        ns = {"d": "http://www.digicol.com/xmlns/dcx"}
        headline = root.findtext("d:head/d:Headline", default="", namespaces=ns)
        title = root.findtext("d:head/d:Title", default="", namespaces=ns) or headline
        title = title or headline or xml_path.stem
        ingredients = []
        for ingredient in root.findall(
            "d:head/d:CustomRecipeIngredients/d:CustomRecipeIngredient",
            ns,
        ):
            name = ingredient.get("plural") or ""
            if name:
                ingredients.append({
                    "name": name,
                    "amount": ingredient.get("amount"),
                    "amount_max": ingredient.get("amount_max") or ingredient.get("max_amount"),
                    "unit": ingredient.get("unit"),
                    "topic": ingredient.get("topic"),
                    "prefix": ingredient.get("prefix"),
                    "suffix": ingredient.get("suffix"),
                    "position": ingredient.get("position"),
                    "error": ingredient.get("ingredient_error"),
                })

        steps = [
            (step.text or "").strip()
            for step in root.findall(
                "d:head/d:CustomRecipePreparationSteps/"
                "d:CustomRecipePreparationsStepsContent",
                ns,
            )
            if (step.text or "").strip()
        ]
        date_created = root.findtext("d:head/d:DateCreated", default="", namespaces=ns)
        date_source = "DateCreated" if date_created else "unknown"
        if not date_created:
            date_created = root.findtext("d:head/d:DateImported", default="", namespaces=ns)
            date_source = "DateImported" if date_created else "unknown"
        if not date_created:
            date_created = root.findtext("d:created", default="", namespaces=ns)
            date_source = "created" if date_created else "unknown"

        return {
            "id": root.get("id"),
            "title": title,
            "subtitle": root.findtext("d:head/d:SubHeadline", default="", namespaces=ns),
            "published": date_created[:10] if date_created else None,
            "publication_date": date_created[:10] if date_created else None,
            "date_source": date_source,
            "ingredients": ingredients,
            "steps": steps,
            "source_path": str(xml_path),
        }

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
                "novelty_score": 50.0,
                "content_gap": "Archive export unavailable; content gap cannot be verified.",
                "assumption": (
                    "The supplied archive export contains topic mappings, not a complete "
                    "recipe export. No claim is made about archive matches."
                ),
            }

        topic_tokens = _topic_tokens(topic)
        matches = []
        for recipe in self.recipes:
            match = _archive_match(topic_tokens, recipe)
            if match is not None:
                matched_recipe = dict(recipe)
                matched_recipe["archive_match_score"] = round(match["score"], 3)
                matched_recipe["match_level"] = match["level"]
                matches.append(matched_recipe)
        matches.sort(
            key=lambda recipe: (
                recipe["match_level"] == "whole",
                recipe["archive_match_score"],
            ),
            reverse=True,
        )

        novelty_score = _novelty_score(matches)
        if not matches:
            risk = "low"
            gap = "No close archived match was found."
            match_status = "no_match_found"
        elif novelty_score < 45:
            risk = "high"
            gap = "Several strong or recent overlaps exist; a clearly differentiated format is required."
            match_status = "matches_found"
        elif novelty_score < 75:
            risk = "medium"
            if any(recipe["match_level"] == "whole" for recipe in matches):
                gap = "Comparable whole-topic recipes exist, but the format or seasonal angle can be differentiated."
            else:
                gap = "The archive contains component-level overlap, but no whole-topic recipe was found."
            match_status = "matches_found"
        else:
            risk = "low"
            gap = "Only limited or weak overlap was found."
            match_status = "matches_found"

        comparable_matches = [
            recipe for recipe in matches if recipe["match_level"] == "whole"
        ] or matches
        dates = [
            recipe.get("published") or recipe.get("publication_date")
            for recipe in comparable_matches
        ]
        dates = [value for value in dates if value]
        recurring_ingredients = sorted({
            (
                ingredient.get("name", "").lower()
                if isinstance(ingredient, dict)
                else str(ingredient).lower()
            )
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
            "similar_recipes": matches[:25],
            "whole_match_count": sum(
                recipe["match_level"] == "whole" for recipe in matches
            ),
            "word_match_count": sum(
                recipe["match_level"] == "word" for recipe in matches
            ),
            "most_recent_comparable_publication": max(dates) if dates else None,
            "recurring_ingredients": recurring_ingredients,
            "recurring_methods": recurring_methods,
            "repetition_risk": risk,
            "novelty_score": round(novelty_score, 1),
            "content_gap": gap,
            "assumption": "Matched against the supplied archive export.",
        }


def _topic_tokens(topic: str) -> set[str]:
    stop_words = {
        "and", "or", "der", "die", "das", "food", "dish", "cabbage", "vegetable",
    }
    return {
        token.rstrip("s")
        for token in re.findall(r"[a-z0-9äöüß]+", topic.casefold())
        if len(token) >= 3 and token not in stop_words
    }


def _recipe_tokens(recipe: dict) -> tuple[set[str], set[str]]:
    title_tokens = {
        token.rstrip("s")
        for token in re.findall(r"[a-z0-9äöüß]+", str(recipe.get("title", "")).casefold())
    }
    ingredient_tokens = set()
    ingredients = recipe.get("ingredients", [])
    if not isinstance(ingredients, list):
        ingredients = str(ingredients).split(",")
    for ingredient in ingredients:
        name = ingredient.get("name", "") if isinstance(ingredient, dict) else str(ingredient)
        ingredient_tokens.update(
            token.rstrip("s")
            for token in re.findall(r"[a-z0-9äöüß]+", name.casefold())
        )
    return title_tokens, ingredient_tokens


def _archive_match(topic_tokens: set[str], recipe: dict) -> dict | None:
    if not topic_tokens:
        return None
    title_tokens, ingredient_tokens = _recipe_tokens(recipe)
    title_overlap = len(topic_tokens & title_tokens) / len(topic_tokens)
    ingredient_overlap = len(topic_tokens & ingredient_tokens) / len(topic_tokens)
    word_overlap = len(topic_tokens & (title_tokens | ingredient_tokens)) / len(topic_tokens)
    if word_overlap == 0:
        return None
    if title_overlap == 1.0:
        return {
            "level": "whole",
            "score": 0.75 * title_overlap + 0.25 * ingredient_overlap,
        }
    return {
        "level": "word",
        "score": 0.35 * title_overlap + 0.15 * ingredient_overlap,
    }


def _novelty_score(matches: list[dict]) -> float:
    if not matches:
        return 100.0
    whole_matches = [
        recipe for recipe in matches if recipe["match_level"] == "whole"
    ]
    word_matches = [
        recipe for recipe in matches if recipe["match_level"] == "word"
    ]
    strongest_whole = max(
        (recipe["archive_match_score"] for recipe in whole_matches),
        default=0.0,
    )
    strongest_word = max(
        (recipe["archive_match_score"] for recipe in word_matches),
        default=0.0,
    )
    whole_volume_pressure = 1 - math.exp(-len(whole_matches) / 3)
    word_volume_pressure = 1 - math.exp(-len(word_matches) / 30)
    recent_pressure = 0.0
    dated_matches = []
    for recipe in matches:
        published = recipe.get("published") or recipe.get("publication_date")
        try:
            dated_matches.append((date.today() - date.fromisoformat(published)).days)
        except (TypeError, ValueError):
            continue
    if dated_matches:
        recent_pressure = max(0.0, 1 - max(0, min(dated_matches)) / (365 * 5))

    # Whole-topic matches are strongest. Word-level matches still matter, but
    # their volume is deliberately capped so a generic ingredient cannot look
    # like an exact duplicate.
    pressure = (
        15 * strongest_whole
        + 38 * whole_volume_pressure
        + 8 * strongest_word
        + 28 * word_volume_pressure
        + 6 * recent_pressure
    )
    return max(0.0, min(100.0, 100.0 - pressure))
