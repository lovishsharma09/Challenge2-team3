from __future__ import annotations

import csv
import json
import hashlib
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
                "content_gap": "Archive export unavailable; content gap cannot be verified.",
                "assumption": (
                    "The supplied archive export contains topic mappings, not a complete "
                    "recipe export. No claim is made about archive matches."
                ),
            }

        keywords = {
            word.strip("(),")
            for word in topic.casefold().replace("_", " ").split()
            if len(word.strip("(),")) >= 3
            and word.strip("(),") not in {"food", "dish", "cabbage", "vegetable"}
        }
        matches = []
        for recipe in self.recipes:
            ingredient_names = []
            for ingredient in recipe.get("ingredients", []):
                if isinstance(ingredient, dict):
                    ingredient_names.append(ingredient.get("name", "").casefold())
                else:
                    ingredient_names.append(str(ingredient).casefold())
            searchable = " ".join([recipe["title"].casefold(), *ingredient_names])
            if any(keyword in searchable for keyword in keywords):
                matches.append(recipe)
            elif keyword_match(topic, recipe["title"]):
                matches.append(recipe)
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
