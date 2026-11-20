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
        return {"source": "mock", "status": "unavailable", "available": False, "match_status": "archive_unavailable",
                "similar_recipes": [], "repetition_risk": "unknown", "content_gap": "", "assumption": "MOCK: export not loaded."}
    if topic == "Quitte":
        return {"source": "mock", "status": "ok", "available": True, "match_status": "no_match_found", "similar_recipes": [],
                "repetition_risk": "low", "content_gap": "MOCK: untouched topic.", "assumption": ""}
    return {"source": "mock", "status": "ok", "available": True, "match_status": "matches_found",
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


def propose_with_archive(archive, base=None):
    """propose() whose archive evidence comes from the REAL local export (trend and brand parts stay mock)."""
    from .archive import lookup
    base = base or propose

    def propose_real_archive(exclude: set[str], limit: int = 5):
        accepted, rejected = base(exclude, limit)
        for p in accepted:
            p["archive"] = lookup(archive, p["topic"])
        return accepted, rejected
    return propose_real_archive


def propose_with_trends(trends_dir, archive=None):
    """propose() built from the PROVIDED Google Trends + Wikimedia data and the real archive lookup.
    Not yet real: brand fit (not assessed) and recipe ideas (empty until the generation step exists)."""
    from . import trends
    from .archive import lookup, load_archive
    data = trends.load_trends(trends_dir)             # raises with a clear message if inputs are missing/malformed
    archive = archive if archive is not None else load_archive(None)

    def propose_from_trends(exclude: set[str], limit: int = 5):
        picked, rejected = trends.select(data, limit, exclude)
        accepted = []
        for rank, (group, comp) in enumerate(picked, start=1):
            accepted.append({
                "id": "p-" + trends_slug(group.topic), "topic": group.topic, "rank": rank,
                "title": f"{group.topic}: neue Rezeptidee", "trend": trends.trend_block(group, comp),
                "brand_fit": {"score": None, "reasoning": "Not assessed yet: the brand guidelines are not applied in this version."},
                "archive": lookup(archive, group.topic), "recipe_ideas": [],
            })
        return accepted, rejected
    propose_from_trends.notes = data.notes
    return propose_from_trends


def trends_slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.casefold().translate(str.maketrans("äöüß", "aous"))).strip("-") or "topic"


MOCK_NOTE_DE = "MOCK-Beispiel zur Probe des Ablaufs (feste Linsensuppen-Rezepte), nicht aus dem gewählten Pitch erzeugt"

# Where the stub reviser puts a forgotten ingredient: (recipe title, ingredient) -> (step index, corrected step text).
# Written like an editor would: the ingredient joins the step where it is actually used, not after serving.
STUB_FIXES = {
    ("Rote Linsensuppe mit Zitrone", "Zitronensaft"): (
        2, "Die Suppe aufkochen und bei mittlerer Hitze 15 Minuten köcheln lassen, bis die Linsen weich sind. Dann fein pürieren "
           "und mit 2 EL Zitronensaft, Salz und Pfeffer abschmecken."),
    ("Linsen-Eintopf mit Kartoffeln", "Lorbeerblatt"): (
        1, "200 g Tellerlinsen und die Kartoffeln zugeben, mit 800 ml Gemüsebrühe aufgießen, 1 Lorbeerblatt zugeben und "
           "25 Minuten köcheln lassen."),
}


def generate(proposal: dict, notes: str = "") -> dict:
    """STUB: always returns two fixed, realistic lentil-soup recipes (flagged mock). Each has one forgotten ingredient, the kind of
    slip the review loop exists to catch. The content does NOT come from the selected pitch."""
    soup = {
        "title": "Rote Linsensuppe mit Zitrone", "subtitle": "Cremig, schnell und alltagstauglich", "servings": 4,
        "prep_time_minutes": 15, "cook_time_minutes": 25, "difficulty": "leicht", "image_url": None, "mock": True,
        "ingredients": [
            {"name": "Olivenöl", "amount": 2, "unit": "EL"}, {"name": "Zwiebel", "amount": 1, "unit": "Stück"},
            {"name": "Knoblauch", "amount": 2, "unit": "Zehen"}, {"name": "Kreuzkümmel", "amount": 1, "unit": "TL"},
            {"name": "rote Linsen", "amount": 250, "unit": "g"}, {"name": "Gemüsebrühe", "amount": 1, "unit": "l"},
            {"name": "Zitronensaft", "amount": 2, "unit": "EL"}, {"name": "Salz", "amount": None, "unit": ""},
            {"name": "Pfeffer", "amount": None, "unit": ""}, {"name": "Petersilie", "amount": 1, "unit": "Bund"}],
        "steps": [
            "Zwiebel und Knoblauch schälen und fein hacken. 2 EL Olivenöl in einem Topf erhitzen und beides 3 Minuten glasig dünsten.",
            "1 TL Kreuzkümmel kurz mitrösten. 250 g rote Linsen gründlich abspülen, dazugeben und mit 1 l Gemüsebrühe aufgießen.",
            "Die Suppe aufkochen und bei mittlerer Hitze 15 Minuten köcheln lassen, bis die Linsen weich sind. Dann fein pürieren "
            "und mit Salz und Pfeffer würzen.",
            "1 Bund Petersilie hacken, über die Suppe streuen und heiß servieren."]}
    stew = {
        "title": "Linsen-Eintopf mit Kartoffeln", "subtitle": "Herzhaft, sättigend und gut vorzubereiten", "servings": 4,
        "prep_time_minutes": 20, "cook_time_minutes": 30, "difficulty": "leicht", "image_url": None, "mock": True,
        "ingredients": [
            {"name": "Olivenöl", "amount": 1, "unit": "EL"}, {"name": "Zwiebel", "amount": 1, "unit": "Stück"},
            {"name": "Karotten", "amount": 2, "unit": "Stück"}, {"name": "Kartoffeln", "amount": 400, "unit": "g"},
            {"name": "Tellerlinsen", "amount": 200, "unit": "g"}, {"name": "Gemüsebrühe", "amount": 800, "unit": "ml"},
            {"name": "Lorbeerblatt", "amount": 1, "unit": "Stück"}, {"name": "Apfelessig", "amount": 1, "unit": "EL"},
            {"name": "Salz", "amount": None, "unit": ""}, {"name": "Pfeffer", "amount": None, "unit": ""}],
        "steps": [
            "Zwiebel und Karotten schälen und würfeln, Kartoffeln in 2 cm große Stücke schneiden. 1 EL Olivenöl erhitzen und Zwiebel "
            "und Karotten darin 5 Minuten anbraten.",
            "200 g Tellerlinsen und die Kartoffeln zugeben, mit 800 ml Gemüsebrühe aufgießen und 25 Minuten köcheln lassen.",
            "Mit 1 EL Apfelessig, Salz und Pfeffer abschmecken und heiß servieren."]}
    return {"proposal_id": proposal["id"], "steering_notes": notes.strip(), "recipes": [soup, stew]}


def review(bundle: dict, notes: str = "") -> list[dict]:
    if "demo-soft" in notes:
        return [{"recipe_index": 0, "criterion": "title",
                 "message": f"{bundle['recipes'][0]['title']}: the title could be more specific."}]
    return []


def revise(proposal: dict, notes: str, bundle: dict, issues: list[dict], comment: str = "") -> dict:
    """STUB reviser: fixes a forgotten ingredient inside the step where it belongs (known sample recipes), otherwise inserts a
    mention BEFORE the final serving step."""
    out = copy.deepcopy(bundle)
    if "demo-stuck" in notes:
        return out
    for issue in issues:
        if issue["criterion"] == "ingredient_unused" and issue["recipe_index"] is not None:
            recipe = out["recipes"][issue["recipe_index"]]
            name = issue["message"].split("'")[1]
            if name.casefold() in " ".join(recipe["steps"]).casefold():
                continue
            fix = STUB_FIXES.get((recipe["title"], name))
            if fix and fix[0] < len(recipe["steps"]):
                recipe["steps"][fix[0]] = fix[1]
            else:
                recipe["steps"].insert(max(len(recipe["steps"]) - 1, 0), f"Mit {name} abschmecken.")
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
    render: Callable | None = None          # optional card exporter; None = editor.render.render_cards
