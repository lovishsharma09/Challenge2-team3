from __future__ import annotations


class ReviewAgent:
    CRITERIA = (
        "ingredients_complete",
        "units_clear",
        "steps_complete",
        "timing_present",
        "two_recipes",
        "differentiation",
        "steering_notes_addressed",
        "nutrition_reference",
    )

    def review(self, recipes: dict, steering_notes: str = "") -> dict:
        issues = []
        for recipe in recipes["recipes"]:
            if not recipe.get("ingredients"):
                issues.append({"criterion": "ingredients_complete", "message": f"{recipe['title']} has no ingredients."})
            if not recipe.get("steps"):
                issues.append({"criterion": "steps_complete", "message": f"{recipe['title']} has no steps."})
            if not recipe.get("prep_time_minutes") or not recipe.get("cook_time_minutes"):
                issues.append({"criterion": "timing_present", "message": f"{recipe['title']} has incomplete timing."})
            if any(item.get("amount") is None or not item.get("unit") for item in recipe.get("ingredients", [])):
                issues.append({"criterion": "units_clear", "message": f"{recipe['title']} contains an unclear unit."})
        if len(recipes["recipes"]) != 2:
            issues.append({"criterion": "two_recipes", "message": "Exactly two recipes are required."})
        titles = [recipe["title"] for recipe in recipes["recipes"]]
        if len(set(titles)) != len(titles):
            issues.append({"criterion": "differentiation", "message": "The recipes are not differentiated."})
        if steering_notes and steering_notes.casefold() not in str(recipes).casefold():
            issues.append({"criterion": "steering_notes_addressed", "message": "Steering notes are not reflected."})

        return {
            "passed": not issues,
            "criteria_checked": list(self.CRITERIA),
            "issues": issues,
            "corrections_made": [],
            "loops_used": 0,
        }
