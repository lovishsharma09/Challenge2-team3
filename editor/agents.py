"""STUB agents for the editor desk. ALL DATA IS MOCK (not from the challenge dataset).
Replace each function with the real agent; keep the signatures from contract.py.

Demo triggers (put in the steering notes):
  "demo-stuck" -> the stub reviser cannot fix problems, so the editor sees blocking hard issues
  "demo-soft"  -> the stub reviewer adds one judgment (soft) issue
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

TOPICS = [
    ("Pastinake", 82, "low"), ("Linsen", 77, "medium"), ("Ofen-Feta", 74, "high"), ("Kürbis", 70, "medium"),
    ("Rotkohl", 66, "low"), ("Grünkohl", 64, "medium"), ("Maronen", 61, "low"), ("Birne", 58, "low"),
    ("Sellerie", 55, "medium"), ("Quitte", 52, "low"), ("Rosenkohl", 50, "medium"), ("Haferflocken", 47, "high"),
]


def archive_for(topic: str, risk: str) -> dict:
    """MOCK archive block incl. the unavailable / no-match states of the handoff contract."""
    if topic == "Haferflocken":
        return {"status": "unavailable", "available": False, "match_status": "archive_unavailable",
                "similar_recipes": [], "repetition_risk": "unknown", "content_gap": "", "assumption": "MOCK: export not loaded."}
    if topic == "Quitte":
        return {"status": "ok", "available": True, "match_status": "no_match_found", "similar_recipes": [],
                "repetition_risk": "low", "content_gap": "MOCK: untouched topic.", "assumption": ""}
    return {"status": "ok", "available": True, "match_status": "matches_found",
            "similar_recipes": [{"title": f"{topic}-Klassiker"}], "repetition_risk": risk,
            "content_gap": f"MOCK: no modern {topic} main course.", "assumption": ""}


def wikimedia_for(topic: str, score: int) -> dict:
    if topic == "Quitte":
        return {"status": "no_article_found", "article": None, "score": None, "points": [], "error": None}
    if topic == "Rosenkohl":
        return {"status": "unavailable", "article": None, "score": None, "points": [], "error": "HTTP 503"}
    return {"status": "available", "article": topic, "score": score - 10, "points": [], "error": None}


def propose(exclude: set[str], limit: int = 5):
    pool = [t for t in TOPICS if t[0] not in exclude]
    accepted = []
    for rank, (topic, score, risk) in enumerate(pool[:limit], start=1):
        accepted.append({
            "id": f"p-{topic.lower()}", "topic": topic, "rank": rank,
            "title": f"{topic}: ein modernes das schmeckt! Rezept",
            "trend": {"score": score, "why_relevant": f"MOCK: rising interest in {topic}.",
                      "wikimedia": wikimedia_for(topic, score)},
            "brand_fit": {"score": 90 - rank * 3, "reasoning": "MOCK: seasonal and everyday-practical."},
            "archive": archive_for(topic, risk),
            "recipe_ideas": [f"{topic} aus dem Ofen", f"{topic}-Bowl"],
        })
    rejected = [{"topic": t[0], "reason": "MOCK: not in the top five."} for t in pool[limit:limit + 2]]
    return accepted, rejected


def generate(proposal: dict, notes: str = "") -> dict:
    topic = proposal["topic"]
    base = lambda title, sub, extra: {  # noqa: E731
        "title": title, "subtitle": sub, "servings": 4, "prep_time_minutes": 15, "cook_time_minutes": 25,
        "ingredients": [{"name": topic, "amount": 500, "unit": "g"}, {"name": "Olivenöl", "amount": 2, "unit": "EL"},
                        {"name": "Petersilie", "amount": 1, "unit": "Bund"}, {"name": "Salz", "amount": None, "unit": ""}],
        "steps": [f"{topic} waschen und in Stücke schneiden.", f"Mit Olivenöl mischen und {extra} garen.", "Servieren."],
        "image_url": None}
    return {"proposal_id": proposal["id"], "steering_notes": notes.strip(),
            "recipes": [base(f"{topic} aus dem Ofen", "MOCK: klassisch", "30 Minuten im Ofen"),
                        base(f"{topic}-Pfanne", "MOCK: schnell", "10 Minuten in der Pfanne")]}


def review(bundle: dict, notes: str = "") -> list[dict]:
    if "demo-soft" in notes:
        return [{"recipe_index": 0, "criterion": "title",
                 "message": f"{bundle['recipes'][0]['title']}: the title could be more specific."}]
    return []


def revise(proposal: dict, notes: str, bundle: dict, issues: list[dict], comment: str = "") -> dict:
    out = copy.deepcopy(bundle)
    if "demo-stuck" in notes:
        return out
    for issue in issues:
        if issue["criterion"] == "ingredient_unused" and issue["recipe_index"] is not None:
            recipe = out["recipes"][issue["recipe_index"]]
            name = issue["message"].split("'")[1]
            if name.casefold() not in " ".join(recipe["steps"]).casefold():
                recipe["steps"].append(f"Mit {name} abschmecken bzw. bestreuen.")
    if comment:
        for recipe in out["recipes"]:
            recipe["subtitle"] += f" [Editor: {comment}]"
    return out


def nutrition(recipe: dict) -> dict:
    return {"status": "pending", "per_serving": None, "assumptions": []}   # never invent values


@dataclass
class Agents:
    propose: Callable = propose
    generate: Callable = generate
    review: Callable = review
    revise: Callable = revise
    nutrition: Callable = nutrition
