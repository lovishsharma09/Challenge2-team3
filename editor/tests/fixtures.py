"""SYNTHETIC Person A batch for tests and local demos. Not real data: every title says so. Field names follow
schemas/proposals.schema.json on origin/main. Archive records include CMS/import dates and a risk label on purpose,
to prove the editor desk never presents them as publication dates or as an assessed repetition risk."""
import copy
import json
from pathlib import Path


def _pitch(rank, topic, angle, archive):
    return {
        "id": f"proposal-{topic.lower()}", "rank": rank, "rank_score": round(90 - rank * 4.5, 1),
        "title": f"{topic}: SYNTHETIC Pitch {rank}", "topic": topic,
        "trend": {"score": 80 - rank, "why_relevant": f"SYNTHETIC: {topic} steigt in den Suchanfragen (Testdaten).",
                  "sources": ["SYNTHETIC Google Trends (Testdaten)"],
                  "points": [{"date": "2026-11-10", "value": 10 * rank, "source": "synthetic"},
                             {"date": "2026-11-17", "value": 12 * rank, "source": "synthetic"}],
                  "sparkline": [10 * rank, 12 * rank],
                  "wikimedia": {"status": "available", "article": topic, "score": 55.0, "points": [], "error": None}},
        "brand_fit": {"score": 80, "fit": "high", "reasoning": f"SYNTHETIC: {topic} passt zu saisonal und alltagstauglich."},
        "archive": archive, "recipe_ideas": [angle, f"{angle} (zweite Variante)"],
    }


def _matches(*titles):
    return {"status": "ok", "available": True, "match_status": "matches_found", "repetition_risk": "high",
            "content_gap": "SYNTHETIC gap", "assumption": "SYNTHETIC archive of 3 fake recipes.",
            "similar_recipes": [{"title": t, "category": "Suppen", "published": "2020-08-01", "date_source": "created"} for t in titles]}


NO_MATCH = {"status": "ok", "available": True, "match_status": "no_match_found", "repetition_risk": "low",
            "content_gap": "", "assumption": "SYNTHETIC", "similar_recipes": []}
UNAVAILABLE = {"status": "unavailable", "available": False, "match_status": "archive_unavailable", "repetition_risk": "unknown",
               "content_gap": "", "assumption": "SYNTHETIC: archive not loaded.", "similar_recipes": []}


def sample_batch() -> dict:
    return {"proposals": [
        _pitch(1, "Pastinake", "Ofen-Pastinaken mit Haselnuss-Dukkah als Beilage zum Sonntagsbraten", _matches("SYNTHETIC Pastinakensuppe", "SYNTHETIC Wurzelgemüse")),
        _pitch(2, "Linsen", "Rotes Linsen-Dal mit Röstzwiebeln in 30 Minuten", _matches("SYNTHETIC Linseneintopf")),
        _pitch(3, "Quitte", "Quittenbrot als Geschenk aus der Küche", NO_MATCH),
        _pitch(4, "Grünkohl", "Grünkohl-Pasta mit gerösteten Walnüssen", UNAVAILABLE),
        _pitch(5, "Maronen", "Maronen-Gnocchi mit Salbeibutter", _matches("SYNTHETIC Maronensuppe")),
    ], "rejected_topics": [{"id": "proposal-dubai", "topic": "Dubai-Schokolade", "reason": "SYNTHETIC: Hype ohne Alltagsbezug."}]}


def write_batch(directory, data=None, name="batch.json") -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(sample_batch() if data is None else data, ensure_ascii=False), encoding="utf-8")
    return path


def mutated(fn):
    data = copy.deepcopy(sample_batch())
    fn(data)
    return data


def a_style_batch() -> dict:
    """SYNTHETIC batch shaped like the first real export from Person A: extra fields (rank_components, rank_method, richer archive
    block), every archive unavailable, template recipe ideas, raw Google entity labels as topics, rejected reasons about the archive."""
    def pitch(rank, topic, wiki_status):
        return {
            "id": "proposal-" + topic.lower().replace(" ", "-").replace("(", "").replace(")", ""), "rank": rank,
            "rank_score": round(81.2 - 8 * (rank - 1), 1), "rank_method": "SYNTHETIC combined score", "rank_components": {"trend": 98, "brand": 74},
            "title": f"{topic}: ein modernes das schmeckt! Rezept", "topic": topic,
            "trend": {"score": 98 - 12 * rank, "why_relevant": f"{topic} shows rising search interest in the supplied Google Trends signal.",
                      "sources": ["Google Trends supplied data"], "points": [{"date": "2026-11-18", "value": 98, "source": "google"}],
                      "sparkline": [98],
                      "wikimedia": {"status": wiki_status, "article": topic.split(" (")[0] if wiki_status == "available" else None,
                                    "score": 28 if wiki_status == "available" else None, "points": [], "error": None,
                                    "period_start": "2026-10-20", "period_end": "2026-11-18", "method": "SYNTHETIC"}},
            "brand_fit": {"score": 74, "fit": "medium", "rules": ["Alltagstauglich"], "positive_signals": [], "negative_signals": [],
                          "reasoning": f"{topic} kann zum Claim 'Der Alltagsbegleiter mit gehobenem Anspruch' passen."},
            "archive": {"status": "archive_unavailable", "available": False, "match_status": "archive_unavailable",
                        "most_recent_comparable_publication": None, "recurring_ingredients": [], "recurring_methods": [],
                        "repetition_risk": "unknown", "similar_recipes": [], "content_gap": "Archive export unavailable.",
                        "assumption": "No claim is made about archive matches."},
            "recipe_ideas": [f"Einfache {topic}-Variante in einem 30-Minuten-Format", f"Saisonale {topic}-Version zum Vorbereiten",
                             f"Klassische {topic}-Version mit klarer Wochenendoption"]}
    topics = [("Cookie (Food)", "available"), ("Biscuit (Food)", "available"), ("Brussels sprout", "no_article_found"),
              ("Curly kale (Vegetable)", "no_article_found"), ("Red cabbage (Cabbage)", "no_article_found")]
    return {"proposals": [pitch(i, t, w) for i, (t, w) in enumerate(topics, 1)],
            "rejected_topics": [{"id": "proposal-x", "topic": "Vanillekipferl", "reason": "Kept outside the shortlist because the archive export is unavailable."}]}


def team_draft_batch() -> dict:
    """SYNTHETIC team draft in the shape of data/local/proposals-review-draft.json: a top-level 'source' block and per-pitch review_notes,
    google_terms, rank_method. Not real data."""
    data = sample_batch()
    data["source"] = {"kind": "team_draft", "label": "Team draft for Deyan's review", "status": "Not approved by Person A",
                      "based_on": {"file": "data/local/proposals.json", "sha256": "ab12cd34ef56" + "0" * 52}, "created": "2026-11-20"}
    for p in data["proposals"]:
        p["rank_method"] = "SYNTHETIC: 50% trend + 30% brand + 20% archive"
        p["trend"]["google_terms"] = [{"term": f"{p['topic'].lower()} rezept", "kind": "query", "signal": "rising",
                                       "search_interest_index": 0, "increase_pct": 850}]
        p["review_notes"] = {"original": {"title": "Original title", "angle": "Einfache X-Variante in einem 30-Minuten-Format",
                                          "why_now": "X shows rising search interest.", "brand_reason": "X kann zum Claim passen."},
                             "changes": ["Title and angle rewritten.", "Archive block replaced by the local lookup."]}
    return data
