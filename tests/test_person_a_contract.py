import unittest
from unittest.mock import patch

from src.challenge2.orchestrator import ChallengeOrchestrator


class PersonAContractTest(unittest.TestCase):
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

    def test_google_trends_score_uses_exported_scale_directly(self):
        from src.challenge2.trend_agent import TrendAgent
        from pathlib import Path

        trend = TrendAgent(Path("data/trends/google-trends"))
        scored = trend.score_topic("Cookie", "98")
        self.assertEqual(scored["trend_score"], 98)

    def test_rank_score_is_transparent_and_not_wikimedia_averaged(self):
        from pathlib import Path
        from src.challenge2.proposal_agent import ProposalAgent

        proposal_agent = ProposalAgent(Path(r"C:\Users\User\Documents\OMMAX Hackathon\auswahl_manifest.json"))
        if not proposal_agent.archive.archive_available:
            self.skipTest("Shared archive not present")
        proposals, _ = proposal_agent.build([{
            "topic": "Cookie (Food)",
            "trend_score": 98,
            "trend_points": [],
            "why_relevant": "Rising.",
            "sources": ["Google Trends supplied data"],
            "wikimedia": {"status": "available", "score": 28},
        }], limit=1)

        proposal = proposals[0]
        self.assertFalse(
            proposal["rank_components"]["wikimedia"]["used_in_numeric_rank"]
        )
        self.assertEqual(proposal["rank_score"], 78.5)
    def test_proposals_have_stable_handoff_fields(self):
        payload = ChallengeOrchestrator().generate_proposals(limit=5)

        ids = [proposal["id"] for proposal in payload["proposals"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(proposal["trend"]["points"] for proposal in payload["proposals"]))
        self.assertTrue(
            all(
                "match_status" in proposal["archive"]
                and "available" in proposal["archive"]
                for proposal in payload["proposals"]
            )
        )

    def test_archive_availability_is_not_conflated_with_no_match(self):
        from src.challenge2.archive_agent import ArchiveAgent

        result = ArchiveAgent().check("unknown seasonal topic")
        self.assertFalse(result["available"])
        self.assertEqual(result["match_status"], "archive_unavailable")
        self.assertIn("archive export", result["assumption"].lower())


if __name__ == "__main__":
    unittest.main()
