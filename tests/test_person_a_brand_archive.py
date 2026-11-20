import json
import tempfile
import unittest
from pathlib import Path

from src.challenge2.archive_agent import ArchiveAgent
from src.challenge2.brand_agent import BrandAgent


class BrandArchiveTest(unittest.TestCase):
    def test_brand_agent_returns_distilled_rules_and_fit(self):
        result = BrandAgent().score("Saisonale regionale Kürbisrezepte")
        self.assertGreaterEqual(result["score"], 80)
        self.assertIn("Saisonaler oder regionaler Bezug", result["rules"])
        self.assertIn("regional", result["positive_signals"])

    def test_archive_unavailable_is_explicit(self):
        result = ArchiveAgent().check("Vanillekipferl")
        self.assertFalse(result["available"])
        self.assertEqual(result["match_status"], "archive_unavailable")
        self.assertEqual(result["similar_recipes"], [])
        self.assertIsNone(result["most_recent_comparable_publication"])

    def test_archive_json_can_find_matches_and_latest_date(self):
        data = [
            {
                "title": "Herbstlicher Kürbisauflauf",
                "published": "2025-10-12",
                "ingredients": ["kürbis", "kartoffel"],
                "method": "Backen",
            },
            {
                "title": "Kürbis-Curry",
                "published": "2026-09-04",
                "ingredients": ["kürbis", "curry"],
                "method": "Schmoren",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = ArchiveAgent(path).check("Kürbis")

        self.assertTrue(result["available"])
        self.assertEqual(result["match_status"], "matches_found")
        self.assertEqual(result["most_recent_comparable_publication"], "2026-09-04")
        self.assertIn("kürbis", result["recurring_ingredients"])
        self.assertGreater(result["novelty_score"], 0)

    def test_one_match_is_not_treated_like_many_matches(self):
        one_data = [
            {
                "title": "Kürbisauflauf",
                "published": "2020-10-12",
                "ingredients": ["kürbis"],
            },
        ]
        many_data = one_data + [
            {
                "title": "Kürbisauflauf mit Käse",
                "published": "2020-10-12",
                "ingredients": ["kürbis"],
            },
            {
                "title": "Kürbisauflauf vegetarisch",
                "published": "2020-10-12",
                "ingredients": ["kürbis"],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            one_path = Path(directory) / "one.json"
            many_path = Path(directory) / "many.json"
            one_path.write_text(json.dumps(one_data), encoding="utf-8")
            many_path.write_text(json.dumps(many_data), encoding="utf-8")
            one_match = ArchiveAgent(one_path).check("Kürbisauflauf")
            many_matches = ArchiveAgent(many_path).check("Kürbisauflauf")

        self.assertEqual(len(one_match["similar_recipes"]), 1)
        self.assertGreater(one_match["novelty_score"], many_matches["novelty_score"])
        self.assertNotEqual(one_match["repetition_risk"], "high")

    def test_multi_word_topic_keeps_generic_word_evidence_separate(self):
        data = [
            {
                "title": "Schokoladenkuchen",
                "published": "2025-01-01",
                "ingredients": ["schokolade"],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = ArchiveAgent(path).check("Dubai Schokolade")

        self.assertEqual(result["match_status"], "matches_found")
        self.assertEqual(result["whole_match_count"], 0)
        self.assertEqual(result["word_match_count"], 1)
        self.assertEqual(result["similar_recipes"][0]["match_level"], "word")
        self.assertLess(result["novelty_score"], 100)

    def test_supplied_manifest_is_loaded_when_available(self):
        manifest = Path(r"C:\Users\User\Documents\OMMAX Hackathon\auswahl_manifest.json")
        if not manifest.exists():
            self.skipTest("Shared archive not present on this machine")
        from src.challenge2.archive_agent import ArchiveAgent

        result = ArchiveAgent(manifest).check("Vanillekipferl")
        self.assertTrue(result["available"])
        self.assertEqual(result["match_status"], "matches_found")
        self.assertGreater(len(result["similar_recipes"]), 0)
        self.assertEqual(result["repetition_risk"], "high")


if __name__ == "__main__":
    unittest.main()
