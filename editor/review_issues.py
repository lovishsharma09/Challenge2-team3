"""Typed review issues. kind: "hard" (verifiable by code, blocks approval) | "soft" (judgment, may be approved).
status: "open" | "fixed" | "dismissed" (dismissal needs an editor reason, audited).

Hard checks: missing quantity (salt/pepper exempt), missing unit, ingredient listed but never used in the steps.
NOT covered yet: quantity/unit mismatch between ingredient list and steps (needs text parsing).
"""
from __future__ import annotations

import re

SALT_PEPPER = ("salz", "pfeffer", "salt", "pepper")


def make_issue(recipe_index, criterion, kind, message):
    return {"key": f"{recipe_index}|{criterion}|{message}", "recipe_index": recipe_index, "criterion": criterion,
            "kind": kind, "message": message, "status": "open", "dismiss_reason": ""}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", text.casefold())


def hard_checks(recipe: dict, index: int) -> list[dict]:
    issues = []
    title = recipe.get("title", f"recipe {index + 1}")
    steps_text = " ".join(recipe.get("steps", [])).casefold()
    step_words = {w for w in _words(steps_text) if len(w) >= 5}
    for ing in recipe.get("ingredients", []):
        name = str(ing.get("name", "")).strip()
        low = name.casefold()
        exempt = any(s in low for s in SALT_PEPPER)
        amount, unit = ing.get("amount"), str(ing.get("unit") or "").strip()
        if amount in (None, "") and not exempt:
            issues.append(make_issue(index, "quantity_missing", "hard", f"{title}: '{name}' has no quantity."))
        elif amount not in (None, "") and not unit:
            issues.append(make_issue(index, "unit_missing", "hard", f"{title}: '{name}' has a quantity but no unit."))
        tokens = [t for t in _words(name) if len(t) >= 4] or [low]
        if not (any(t in steps_text for t in tokens) or any(w in low for w in step_words)):
            issues.append(make_issue(index, "ingredient_unused", "hard",
                                     f"{title}: '{name}' is listed but never used in the steps."))
    return issues


def review_all(agents, bundle: dict, notes: str) -> list[dict]:
    issues = []
    for i, recipe in enumerate(bundle["recipes"]):
        issues.extend(hard_checks(recipe, i))
    for f in agents.review(bundle, notes):
        issues.append(make_issue(f.get("recipe_index"), f["criterion"], "soft", f["message"]))
    return issues
