"""Our contract between the editor workflow and the agents (plain dicts). Independent of any other code.

Proposal:  id, topic, title, rank,
           trend {score, why_relevant}, brand_fit {score, reasoning},
           archive {similar_recipes: [{title}], repetition_risk, content_gap}, recipe_ideas [str]
Bundle:    proposal_id, steering_notes, recipes [Recipe, Recipe]
Recipe:    title, subtitle, servings, prep_time_minutes, cook_time_minutes,
           ingredients [{name, amount|None, unit}], steps [str], image_url|None
Issue:     key, recipe_index|None, criterion, kind (hard|soft), message, status (open|fixed|dismissed), dismiss_reason
Nutrition: {status: "ok"|"pending", per_serving: {kcal, fat_g, carbs_g, protein_g}|None,
            assumptions: [{original, used, confidence}]}   # never invent values: None when unknown

Agents (editor/agents.py, replaced by the real ones later), all plain callables:
  propose(exclude: set[str], limit: int) -> (accepted: [Proposal], rejected: [{topic, reason}])
  generate(proposal, notes) -> Bundle
  review(bundle, notes) -> [{recipe_index, criterion, message}]     # judgment (soft) findings only
  revise(proposal, notes, bundle, issues, comment) -> Bundle
  nutrition(recipe) -> Nutrition
Hard issues (missing quantity/unit, unused ingredient) are always computed by code in review_issues.py.
"""
from __future__ import annotations

PROPOSAL_KEYS = {"id", "topic", "title", "rank", "trend", "brand_fit", "archive", "recipe_ideas"}
RECIPE_KEYS = {"title", "servings", "ingredients", "steps"}


def check_proposals(result) -> tuple[list[dict], list[dict]]:
    accepted, rejected = result
    if not accepted:
        raise ValueError("no proposals returned")
    for p in accepted:
        missing = PROPOSAL_KEYS - set(p)
        if missing:
            raise ValueError(f"proposal {p.get('id')} is missing {sorted(missing)}")
    return accepted, rejected


def check_bundle(bundle: dict) -> dict:
    recipes = bundle.get("recipes") if isinstance(bundle, dict) else None
    if not isinstance(recipes, list) or len(recipes) != 2:
        raise ValueError("a bundle must contain exactly two recipes")
    for r in recipes:
        missing = RECIPE_KEYS - set(r)
        if missing:
            raise ValueError(f"recipe '{r.get('title')}' is missing {sorted(missing)}")
        if not r["ingredients"] or not r["steps"]:
            raise ValueError(f"recipe '{r.get('title')}' has no ingredients or no steps")
    return bundle
