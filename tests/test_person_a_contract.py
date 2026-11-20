import unittest

from src.challenge2.orchestrator import ChallengeOrchestrator


class PersonAContractTest(unittest.TestCase):
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
        self.assertIn(result["match_status"], {"no_match_found", "matches_found"})
        self.assertIn("archive export", result["assumption"].lower())


if __name__ == "__main__":
    unittest.main()
