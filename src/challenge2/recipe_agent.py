from __future__ import annotations

from typing import Any


class RecipeAgent:
    def generate(self, proposal: dict, steering_notes: str = "") -> dict:
        topic = proposal["topic"]
        notes = steering_notes.strip()
        second_variant = "one-pan" if "weeknight" not in notes.casefold() else "weeknight"
        return {
            "proposal_id": proposal["id"],
            "steering_notes": notes,
            "recipes": [
                {
                    "title": f"{topic} auf klassische Art",
                    "subtitle": "Vertraut, warm und alltagsnah",
                    "servings": 4,
                    "prep_time_minutes": 15,
                    "cook_time_minutes": 25,
                    "difficulty": "mittel",
                    "ingredients": [
                        {"name": "Mehl", "amount": 250, "unit": "g"},
                        {"name": "Butter", "amount": 120, "unit": "g"},
                        {"name": "Vanille", "amount": 1, "unit": "TL"},
                        {"name": "Agavensirup", "amount": 80, "unit": "g"},
                    ],
                    "steps": [
                        "Alle Zutaten bereitstellen und den Ofen auf 180 Grad vorheizen.",
                        "Mehl und Gewürze mischen, Butter und Sirup gründlich einarbeiten.",
                        "Die Masse backen, bis sie goldbraun ist.",
                        "Vor dem Servieren vollständig abkühlen lassen.",
                    ],
                    "image_prompt": f"A warm editorial overhead photograph of {topic}, German home-cooking style",
                    "image_url": None,
                },
                {
                    "title": f"{topic} – die {second_variant} Variante",
                    "subtitle": "Schneller umgesetzt, bewusst anders gestaltet",
                    "servings": 4,
                    "prep_time_minutes": 10,
                    "cook_time_minutes": 20,
                    "difficulty": "leicht",
                    "ingredients": [
                        {"name": "Mehl", "amount": 200, "unit": "g"},
                        {"name": "Butter", "amount": 80, "unit": "g"},
                        {"name": "Vanille", "amount": 1, "unit": "TL"},
                    ],
                    "steps": [
                        "Backblech vorbereiten und den Ofen vorheizen.",
                        "Die Zutaten zu einer kompakten Masse verarbeiten.",
                        "Klein portionieren und im Ofen goldbraun backen.",
                    ],
                    "image_prompt": f"A bright modern {topic} recipe in an overhead one-pan format",
                    "image_url": None,
                },
            ],
        }
