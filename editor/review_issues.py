"""Typed review issues. kind: "hard" (verifiable by code, blocks approval) | "soft" (judgment, may be approved).
status: "open" | "fixed" | "dismissed" (dismissal needs an editor reason, audited).

Hard checks: missing quantity (salt/pepper exempt), missing unit, ingredient listed but never used in the steps.
Also: quantity/unit mismatch between the list and the steps. Conservative (only what code can prove):
  - tbsp/tsp mix-up (EL vs TL) for the same ingredient            -> unit_mismatch
  - step amounts of an ingredient (same unit) add up to MORE than the listed amount -> quantity_mismatch
Amounts split over several steps are fine as long as their sum does not exceed the list.
Not covered: unit conversions (g vs ml), fractions written as words, ingredients mentioned without an amount.
"""
from __future__ import annotations

import re

SALT_PEPPER = ("salz", "pfeffer", "salt", "pepper")


# Families group equivalent code checks coming from different sources (ours and Person C's review) so one problem is reported once.
FAMILY = {"ingredient_unused": "unused", "quantity_missing": "quantity", "unit_missing": "quantity",
          "unit_mismatch": "units", "quantity_mismatch": "units"}


def make_issue(recipe_index, criterion, kind, message, family=None):
    return {"key": f"{recipe_index}|{criterion}|{message}", "recipe_index": recipe_index, "criterion": criterion,
            "kind": kind, "message": message, "status": "open", "dismiss_reason": "",
            "family": family or FAMILY.get(criterion, "")}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", text.casefold())


STEP_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(EL|TL|kg|g|ml|l|Bund|Prise|Stück)\b\.?\s+([A-Za-zäöüÄÖÜß][\wäöüÄÖÜß-]*)")


# "je 1 TL Senf (insgesamt 4 TL)", "pro Portion", "zusammen": amounts stated per item or as a total cannot be summed reliably, so no quantity verdict.
PER_ITEM = re.compile(r"\b(je|jeweils|pro|insgesamt|gesamt|zusammen|davon|each|total)\b", re.I)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def mismatch_checks(recipe: dict, index: int) -> list[dict]:
    issues = []
    title = recipe.get("title", f"recipe {index + 1}")
    found: dict[str, dict[str, float]] = {}            # ingredient name -> {unit: summed amount in steps}
    per_item: set[str] = set()                         # ingredients whose amounts are stated per item or as a total somewhere
    for step in recipe.get("steps", []):
        for amount, unit, word in STEP_AMOUNT.findall(step):
            for ing in recipe.get("ingredients", []):
                name = str(ing.get("name", ""))
                if word.casefold() in name.casefold() or name.casefold() in word.casefold():
                    if PER_ITEM.search(step):
                        per_item.add(name)
                    per_unit = found.setdefault(name, {})
                    per_unit[unit.upper() if unit.upper() in ("EL", "TL") else unit] = (
                        per_unit.get(unit.upper() if unit.upper() in ("EL", "TL") else unit, 0.0) + _num(amount))
    for ing in recipe.get("ingredients", []):
        name, amount = str(ing.get("name", "")), ing.get("amount")
        unit = str(ing.get("unit") or "").strip()
        unit_key = unit.upper() if unit.upper() in ("EL", "TL") else unit
        per_unit = found.get(name)
        if not per_unit or amount in (None, ""):
            continue
        for step_unit, total in per_unit.items():
            if {step_unit, unit_key} == {"EL", "TL"}:
                issues.append(make_issue(index, "unit_mismatch", "hard",
                                         f"{title}: '{name}' is listed in {unit} but the steps use {step_unit} (tbsp/tsp mix-up)."))
            elif step_unit == unit_key and total > float(amount) + 1e-9 and name not in per_item:
                issues.append(make_issue(index, "quantity_mismatch", "hard",
                                         f"{title}: the steps use {total:g} {unit} '{name}' but the list has only {amount} {unit}."))
    return issues


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
        elif amount not in (None, "") and not unit and not ing.get("countable"):      # "2 Zwiebeln": a count needs no unit
            issues.append(make_issue(index, "unit_missing", "hard", f"{title}: '{name}' has a quantity but no unit."))
        tokens = [t for t in _words(name) if len(t) >= 4] or [low]
        if not (any(t in steps_text for t in tokens) or any(w in low for w in step_words)):
            issues.append(make_issue(index, "ingredient_unused", "hard",
                                     f"{title}: '{name}' is listed but never used in the steps."))
    return issues + mismatch_checks(recipe, index)


def review_all(agents, bundle: dict, notes: str) -> list[dict]:
    issues = []
    for i, recipe in enumerate(bundle["recipes"]):
        issues.extend(hard_checks(recipe, i))
    for f in agents.review(bundle, notes):
        kind = "hard" if f.get("kind") == "hard" else "soft"           # an agent may report code-verified (hard) findings too
        family = f.get("family") or ""
        if kind == "hard" and family and any(i["kind"] == "hard" and i["recipe_index"] == f.get("recipe_index") and i["family"] == family
                                             for i in issues):
            continue                                                    # the same kind of problem is already reported by our own check
        issues.append(make_issue(f.get("recipe_index"), f["criterion"], kind, f["message"], family))
    return issues
