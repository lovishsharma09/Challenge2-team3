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


if __name__ == "__main__":
    unittest.main()
