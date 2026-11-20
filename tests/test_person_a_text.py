"""Person A's LLM text pass (proposal_llm.py): grounded German titles/ideas with a template fallback, risks from evidence only."""
import unittest

from src.challenge2 import proposal_llm as pl


def proposal(**over) -> dict:
    p = {"id": "proposal-cookie-food", "title": "Cookie (Food): ein modernes das schmeckt! Rezept", "topic": "Cookie (Food)", "rank": 1,
         "trend": {"score": 98, "why_relevant": "Cookie (Food) shows rising search interest in the supplied Google Trends signal.",
                   "sources": ["Google Trends supplied data"], "points": [{"date": "2026-11-18", "value": 98, "source": "Google Trends Rising Topics", "increase_percent": "90 %"}],
                   "wikimedia": {"status": "no_article_found", "article": "Cookie", "score": None, "points": [], "error": "none"}},
         "brand_fit": {"score": 74, "fit": "medium", "reasoning": "Passt.", "positive_signals": [], "negative_signals": []},
         "archive": {"status": "available", "available": True, "match_status": "matches_found", "repetition_risk": "high",
                     "similar_recipes": [{"title": "Haferkekse", "published": "2025-11-01"}], "most_recent_comparable_publication": "2025-11-01",
                     "recurring_ingredients": ["mehl", "butter"], "content_gap": "Keine Weihnachtsplätzchen mit Mandeln."},
         "recipe_ideas": ["Einfache Cookie (Food)-Variante in einem 30-Minuten-Format", "Saisonale Cookie (Food)-Version zum Vorbereiten"]}
    p.update(over)
    return p


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def chat_json(self, system, user, *, validate=None, retries=2, temperature=0.4):
        self.calls += 1
        for r in self.replies:
            if not (validate(r) if validate else []):
                return r
        raise RuntimeError("no valid reply")


class TextPass(unittest.TestCase):
    def test_validation_rejects_labels_templates_and_claims(self):
        bad = [{"title": "Cookie (Food): ein modernes das schmeckt! Rezept", "recipe_ideas": ["a" * 20, "b" * 20], "why_now": "x" * 30},
               {"title": "Mandel-Plätzchen für den Advent", "recipe_ideas": ["Einfache Cookie-Variante in einem 30-Minuten-Format", "b" * 20], "why_now": "x" * 30},
               {"title": "Mandel-Plätzchen für den Advent", "recipe_ideas": ["a" * 20], "why_now": "x" * 30},
               {"title": "Detox-Kekse für die Gesundheit", "recipe_ideas": ["a" * 20, "b" * 20], "why_now": "x" * 30}]
        for obj in bad:
            self.assertTrue(pl.validate_text(obj), obj)
        good = {"title": "Mandel-Plätzchen mit Zimt für den Advent", "recipe_ideas": ["Knusprige Mandelplätzchen aus Mürbeteig, im Ofen gebacken",
                                                                                      "Weiche Haferkekse mit Äpfeln aus der Pfanne"],
                "why_now": "Das Suchinteresse an Plätzchen steigt im November um 90 %."}
        self.assertEqual(pl.validate_text(good), [])

    def test_llm_text_replaces_templates_and_keeps_the_original(self):
        p = proposal()
        good = {"title": "Mandel-Plätzchen mit Zimt für den Advent", "recipe_ideas": ["Knusprige Mandelplätzchen aus Mürbeteig, im Ofen gebacken",
                                                                                      "Weiche Haferkekse mit Äpfeln aus der Pfanne"],
                "why_now": "Das Suchinteresse an Plätzchen steigt im November um 90 %."}
        client = FakeClient([{"title": "Cookie (Food) Rezept", "recipe_ideas": [], "why_now": ""}, good])
        self.assertTrue(pl.enrich_proposal(client, p, brand="Regeln"))
        self.assertEqual(p["title"], good["title"])
        self.assertEqual(p["recipe_ideas"], good["recipe_ideas"])
        self.assertEqual(p["trend"]["why_relevant"], good["why_now"])
        self.assertEqual(p["text_source"], "llm")
        self.assertEqual(p["text_original"]["title"], "Cookie (Food): ein modernes das schmeckt! Rezept")
        self.assertEqual(p["rank"], 1)                                   # scoring fields untouched

    def test_failing_llm_keeps_the_template(self):
        p = proposal()
        self.assertFalse(pl.enrich_proposal(FakeClient([]), p))
        self.assertEqual(p["title"], "Cookie (Food): ein modernes das schmeckt! Rezept")
        self.assertNotIn("text_original", p)

    def test_no_client_means_templates_for_all(self):
        import os
        os.environ["OFFLINE"] = "1"
        try:
            props = [proposal(), proposal(id="p2")]
            self.assertEqual(pl.enrich_payload(props), 0)
            self.assertTrue(all(p["text_source"] == "template" for p in props))
        finally:
            os.environ.pop("OFFLINE", None)

    def test_evidence_brief_is_text_only_and_german_topic(self):
        b = pl.evidence_brief(proposal())
        self.assertEqual(b["topic_german"], "Plätzchen / Kekse")
        self.assertEqual(b["google_increase"], "90 %")
        self.assertNotIn("points", str(b["wikipedia"]))
        self.assertEqual(b["archive"]["similar_total"], 1)

    def test_risks_come_from_the_evidence(self):
        risks = pl.evidence_risks(proposal())
        self.assertTrue(any("Wiederholungsrisiko high" in r for r in risks))
        self.assertTrue(any("Wikipedia" in r for r in risks))
        self.assertTrue(any("Vorlagen" in r for r in risks))
        self.assertFalse(any("Google-Suchinteresse nur" in r for r in risks))      # 98/100 is not low
        self.assertEqual(pl.evidence_risks(proposal(text_source="llm", trend={"score": 80, "wikimedia": {"status": "available"}},
                                                    archive={"match_status": "no_match_found", "available": True, "similar_recipes": [], "repetition_risk": "low"},
                                                    brand_fit={"fit": "high"})), [])


if __name__ == "__main__":
    unittest.main()
