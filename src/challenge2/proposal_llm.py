"""Concrete German proposal texts for the five pitches, plus deterministic risk bullets.

The template titles ("Cookie (Food): ein modernes das schmeckt! Rezept") and placeholder angles
("Einfache X-Variante in einem 30-Minuten-Format") are rewritten by the gateway LLM, grounded ONLY in the
evidence this pipeline collected (Google Trends row, Wikipedia pageviews, brand-fit reasoning, archive matches)
and the brand rules. The ranking, scores and evidence blocks are never touched; the original texts are kept under
`text_original`. If the LLM is not configured or fails, the templates stay (text_source = "template").
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSON_C_SRC = ROOT / "person_c" / "src"
RISING_QUERIES = ROOT / "data" / "trends" / "google-trends" / "searched_with_rising-searches_queries_DE_20261018-1818_20261118-1818.csv"
BRAND_RULES_JSON = ROOT / "person_c" / "assets" / "brand_rules.default.json"
LABEL_RE = re.compile(r"\s*\((Food|Vegetable|Fruit|Dish|Meal|Cake|Cabbage|Confectionery)\)\s*", re.I)
# Google's topic labels are English; the German reader term is the grounding the writer needs.
GERMAN_TOPIC = {
    "cookie": "Plätzchen / Kekse", "biscuit": "Kekse", "brussels sprout": "Rosenkohl", "curly kale": "Grünkohl",
    "savoy cabbage": "Wirsing", "gingerbread": "Lebkuchen", "almond": "Mandeln", "red cabbage": "Rotkohl",
    "stollen": "Stollen", "chocolate cake": "Schokoladenkuchen", "rinderroulade": "Rinderroulade", "vanillekipferl": "Vanillekipferl",
    "pancake": "Pfannkuchen", "cake": "Kuchen", "pumpkin": "Kürbis", "chestnut": "Maronen", "goose": "Gans", "duck": "Ente",
}
TEMPLATE_ANGLE = re.compile(r"^(Einfache|Saisonale|Klassische) .+(-Variante in einem 30-Minuten-Format|-Version zum Vorbereiten|-Version mit klarer Wochenendoption)$")
FORBIDDEN = re.compile(r"superfood|detox|gesund(heit)?s?|abnehm|diät|heil", re.I)
SYSTEM = ("Du bist Redakteur:in der deutschen Kochzeitschrift 'das schmeckt!'. Du formulierst Rezeptvorschläge nur aus den "
          "gelieferten Belegen; du erfindest keine Fakten, Zahlen oder Herkunftsgeschichten. Antworte mit genau einem JSON-Objekt.")


def german_topic(topic: str) -> str:
    base = LABEL_RE.sub("", topic).strip()
    return GERMAN_TOPIC.get(base.casefold(), base)


def related_queries(topic: str, limit: int = 6) -> list[dict]:
    """Rising German search queries that mention the topic (or its German term). Evidence, not invention."""
    if not RISING_QUERIES.is_file():
        return []
    terms = {w for w in re.findall(r"[a-zäöüß]{4,}", (LABEL_RE.sub("", topic) + " " + german_topic(topic)).casefold())}
    out = []
    with RISING_QUERIES.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            q = row.get("query", "")
            if any(t in q.casefold() for t in terms):
                out.append({"query": q, "search_interest": row.get("search interest"), "increase": row.get("increase percent")})
    return out[:limit]


def brand_rules_text() -> str:
    try:
        rules = json.loads(BRAND_RULES_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Alltagstauglich, saisonal/regional, kurze Zutatenliste, Fleisch und Klassiker bevorzugt, keine exotischen Zutaten."
    parts = [f"Claim: {rules.get('claim', '')}", f"Zielgruppe: {rules.get('audience', '')}"]
    for key, label in (("interest_high", "Hohes Interesse"), ("no_interest", "Kein Interesse"), ("must", "Muss"), ("avoid", "Vermeiden")):
        if rules.get(key):
            parts.append(f"{label}: " + "; ".join(rules[key]))
    return "\n".join(parts)


def evidence_brief(p: dict) -> dict:
    """Everything the writer may use – nothing else exists for it."""
    t, a, b = p.get("trend") or {}, p.get("archive") or {}, p.get("brand_fit") or {}
    pts = t.get("points") or []
    wiki = t.get("wikimedia") or {}
    sim = [r for r in (a.get("similar_recipes") or []) if isinstance(r, dict)]
    return {
        "topic_google": p.get("topic"), "topic_german": german_topic(p.get("topic", "")),
        "google_search_interest_0_100": t.get("score"),
        "google_increase": (pts[0].get("increase_percent") if pts and isinstance(pts[0], dict) else None),
        "google_period": "2026-10-18 bis 2026-11-18", "related_rising_queries": related_queries(p.get("topic", "")),
        "wikipedia": {"status": wiki.get("status"), "article": wiki.get("article"), "change_score_0_100": wiki.get("score")},
        "brand_fit": {"score": b.get("score"), "fit": b.get("fit"), "reasoning": b.get("reasoning"),
                      "positive_signals": b.get("positive_signals"), "negative_signals": b.get("negative_signals")},
        "archive": {"match_status": a.get("match_status"), "repetition_risk": a.get("repetition_risk"),
                    "similar_recipes": [{"title": r.get("title"), "published": r.get("published")} for r in sim[:8]],
                    "similar_total": len(sim), "most_recent_comparable_publication": a.get("most_recent_comparable_publication"),
                    "recurring_ingredients": (a.get("recurring_ingredients") or [])[:10], "content_gap": a.get("content_gap")},
    }


def validate_text(obj) -> list[str]:
    errs = []
    if not isinstance(obj, dict):
        return ["JSON-Objekt erwartet"]
    title = obj.get("title")
    if not isinstance(title, str) or not 8 <= len(title.strip()) <= 80:
        errs.append("title: 8-80 Zeichen")
    elif LABEL_RE.search(title) or re.search(r"\b(Food|Vegetable|modernes das schmeckt)\b", title):
        errs.append("title: deutscher Rezepttitel ohne englisches Themenlabel")
    ideas = obj.get("recipe_ideas")
    if not isinstance(ideas, list) or len(ideas) != 2 or not all(isinstance(i, str) and 15 <= len(i.strip()) <= 160 for i in ideas):
        errs.append("recipe_ideas: genau 2 konkrete Ideen à 15-160 Zeichen")
    elif any(TEMPLATE_ANGLE.match(i.strip()) for i in ideas):
        errs.append("recipe_ideas: keine Platzhalter")
    why = obj.get("why_now")
    if not isinstance(why, str) or not 20 <= len(why.strip()) <= 300:
        errs.append("why_now: ein Satz, 20-300 Zeichen")
    text = " ".join(str(x) for x in [title, why, *(ideas if isinstance(ideas, list) else [])])
    if FORBIDDEN.search(text):
        errs.append("keine Gesundheits-/Diätversprechen")
    return errs


def llm_client():
    """Person C's gateway client (same .env). None when not configured or in offline/mock mode."""
    if str(PERSON_C_SRC) not in sys.path:
        sys.path.insert(0, str(PERSON_C_SRC))
    try:
        from c_pipeline.config import Config
        from c_pipeline.llm import OpenAICompatClient
        cfg = Config.from_env()
        if cfg.offline or not (cfg.llm_base_url and cfg.llm_model):
            return None
        cfg.llm_timeout = 90
        return OpenAICompatClient(cfg)
    except Exception:  # noqa: BLE001 – no LLM means templates, never a crash
        return None


def enrich_proposal(client, p: dict, brand: str | None = None) -> bool:
    """Rewrite title / recipe_ideas / why_now in place. Returns True when the LLM text was used."""
    brief = evidence_brief(p)
    user = ("Belege (JSON):\n" + json.dumps(brief, ensure_ascii=False, indent=1) +
            "\n\nMarkenregeln:\n" + (brand or brand_rules_text()) +
            "\n\nAufgabe: Formuliere für dieses Thema einen konkreten deutschen Rezeptvorschlag für das Heft. "
            "Nur aus den Belegen oben: nenne keine Zutaten, Zahlen oder Trends, die dort nicht stehen; das Archiv zeigt, was es "
            "schon gab – schlage etwas vor, das die Lücke (content_gap) füllt und die Wiederholung vermeidet. "
            "Alltagstauglich, Zutaten aus dem Supermarkt, keine Gesundheitsversprechen, kein Marketing-Ton.\n"
            'Antworte NUR mit JSON: {"title": "<deutscher Rezepttitel, 4-10 Wörter, z. B. \'Grünkohl-Eintopf mit Kassler\'>", '
            '"recipe_ideas": ["<Idee 1: Gericht + Hauptzutaten + Zubereitungsart>", "<Idee 2, klar anders als Idee 1>"], '
            '"why_now": "<ein Satz, warum jetzt – nur aus den Belegen>"}')
    try:
        obj = client.chat_json(SYSTEM, user, validate=validate_text, retries=2, temperature=0.4)
    except Exception:  # noqa: BLE001
        return False
    p["text_original"] = {"title": p.get("title"), "recipe_ideas": list(p.get("recipe_ideas") or []),
                          "why_relevant": (p.get("trend") or {}).get("why_relevant")}
    p["title"] = " ".join(obj["title"].split())
    p["recipe_ideas"] = [" ".join(i.split()) for i in obj["recipe_ideas"]]
    if isinstance(p.get("trend"), dict):
        p["trend"]["why_relevant"] = " ".join(obj["why_now"].split())
    p["text_source"] = "llm"
    return True


def enrich_payload(proposals: list[dict], progress=None) -> int:
    """All five pitches; each one falls back to its template text on its own. Returns the number rewritten."""
    tell = progress or (lambda message: None)
    client = llm_client()
    if client is None:
        for p in proposals:
            p.setdefault("text_source", "template")
        return 0
    brand = brand_rules_text()
    done = 0
    for p in proposals:
        tell(f"Writing a concrete German pitch for {german_topic(p.get('topic', ''))}")
        if enrich_proposal(client, p, brand):
            done += 1
        else:
            p["text_source"] = "template"
    return done


def evidence_risks(p: dict) -> list[str]:
    """Risk bullets computed from the evidence only (never from the LLM)."""
    t, a, b = p.get("trend") or {}, p.get("archive") or {}, p.get("brand_fit") or {}
    risks = []
    sim = [r for r in (a.get("similar_recipes") or []) if isinstance(r, dict)]
    if a.get("match_status") == "archive_unavailable" or a.get("available") is False:
        risks.append("Archiv nicht verfügbar: Wiederholungen konnten nicht geprüft werden.")
    elif a.get("repetition_risk") in ("high", "medium") and sim:
        latest = a.get("most_recent_comparable_publication")
        risks.append(f"Wiederholungsrisiko {a.get('repetition_risk')}: {len(sim)} vergleichbare Archivrezepte"
                     + (f", zuletzt {latest}" if latest else "") + ".")
    score = t.get("score")
    if isinstance(score, (int, float)) and score < 30:
        risks.append(f"Google-Suchinteresse nur {score:.0f}/100 (relativer Index, kleine Basis).")
    wiki = t.get("wikimedia") or {}
    if wiki.get("status") != "available":
        risks.append("Kein Wikipedia-Seitenaufruf-Beleg (" + {"no_article_found": "kein Artikel gefunden", "no_data": "keine Daten",
                                                               "unavailable": "Quelle nicht erreichbar"}.get(wiki.get("status"), "nicht geprüft") + ").")
    if b.get("fit") == "low":
        risks.append("Geringer Marken-Fit laut Regelwerk.")
    if b.get("negative_signals"):
        risks.append("Negative Markensignale: " + ", ".join(b["negative_signals"]) + ".")
    if p.get("text_source", "template") == "template":
        risks.append("Titel und Rezeptideen sind noch Vorlagen (LLM-Text nicht verfügbar).")
    return risks


def add_risks(proposals: list[dict]) -> None:
    for p in proposals:
        p["risks"] = evidence_risks(p)
