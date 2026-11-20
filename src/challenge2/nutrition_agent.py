from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


UNIT_TO_GRAMS = {
    "g": 1.0,
    "gramm": 1.0,
    "kg": 1000.0,
    "ml": 1.0,
    "l": 1000.0,
    "el": 15.0,
    "tl": 5.0,
    "prise": 1.0,
    "stück": 100.0,
}


class NutritionAgent:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.rows = self._load()

    def _load(self) -> list[dict[str, str]]:
        with self.database_path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.readlines()
        from io import StringIO

        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("ID;")
        )
        return list(
            csv.DictReader(
                StringIO("".join(lines[header_index:])),
                delimiter=";",
            )
        )

    def match(self, ingredient_name: str) -> dict | None:
        normalized = ingredient_name.casefold().strip()
        for row in self.rows:
            name = (row.get("Name") or "").casefold()
            synonyms = (row.get("Synonyme") or "").casefold()
            if normalized == name or normalized in {item.strip() for item in synonyms.split(";")}:
                return row
        for row in self.rows:
            name = (row.get("Name") or "").casefold()
            if normalized and normalized in name:
                return row
        return None

    def calculate(self, ingredients: Iterable[dict], servings: int) -> dict:
        matches = []
        totals = {"kcal": 0.0, "fat_g": 0.0, "carbs_g": 0.0, "protein_g": 0.0}
        for ingredient in ingredients:
            name = ingredient["name"]
            amount = float(ingredient.get("amount", 0))
            unit = str(ingredient.get("unit", "g")).casefold()
            grams = amount * UNIT_TO_GRAMS.get(unit, 1.0)
            row = self.match(name)
            if row is None:
                matches.append({
                    "ingredient": name,
                    "matched": False,
                    "confidence": 0.0,
                    "assumption": f"Kein Datenbanktreffer; Nährwerte nicht geschätzt.",
                })
                continue

            factor = grams / 100.0
            try:
                kcal = float((row.get("Energie, Kilokalorien (kcal)") or "0").replace(",", ".")) * factor
                fat = float((row.get("Fett, total (g)") or "0").replace(",", ".")) * factor
                carbs = float((row.get("Kohlenhydrate, verfügbar (g)") or "0").replace(",", ".")) * factor
                protein = float((row.get("Protein (g)") or "0").replace(",", ".")) * factor
            except ValueError:
                kcal = fat = carbs = protein = 0.0
            totals["kcal"] += kcal
            totals["fat_g"] += fat
            totals["carbs_g"] += carbs
            totals["protein_g"] += protein
            matches.append({
                "ingredient": name,
                "matched": True,
                "database_name": row.get("Name"),
                "grams_assumed": round(grams, 1),
                "confidence": 0.95 if unit in {"g", "kg"} else 0.75,
                "assumption": f"{amount} {unit} wurde als {grams:.1f} g angenommen.",
            })

        divisor = max(1, servings)
        return {
            "reference": "per serving",
            "servings": divisor,
            "per_serving": {
                key: round(value / divisor, 1)
                for key, value in totals.items()
            },
            "matches": matches,
        }
