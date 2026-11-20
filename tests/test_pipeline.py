import unittest
from pathlib import Path
from unittest.mock import patch

from src.challenge2.orchestrator import ChallengeOrchestrator


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.brave_patch = patch(
            "src.challenge2.trend_agent.brave_web_search",
            return_value=[],
        )
        self.wikimedia_patch = patch(
            "src.challenge2.trend_agent.WikimediaAgent.fetch_pageviews",
            return_value={
                "status": "no_article_found",
                "article": "test",
                "points": [],
                "error": "Test fixture",
            },
        )
        self.brave_patch.start()
        self.wikimedia_patch.start()

    def tearDown(self):
        self.wikimedia_patch.stop()
        self.brave_patch.stop()
    def test_proposal_pipeline_returns_five(self):
        orchestrator = ChallengeOrchestrator()
        payload = orchestrator.generate_proposals(limit=5)
        self.assertEqual(len(payload["proposals"]), 5)
        self.assertEqual(
            [item["rank"] for item in payload["proposals"]],
            [1, 2, 3, 4, 5],
        )

    def test_end_to_end_recipe_review_and_render(self):
        orchestrator = ChallengeOrchestrator()
        payload = orchestrator.generate_proposals(limit=5)
        result = orchestrator.generate_recipes(
            payload["proposals"][0],
            "weeknight-friendly",
        )
        self.assertEqual(len(result["recipes"]["recipes"]), 2)
        self.assertTrue(result["review"]["passed"])
        self.assertTrue(Path(result["output_html"]).exists())


if __name__ == "__main__":
    unittest.main()
