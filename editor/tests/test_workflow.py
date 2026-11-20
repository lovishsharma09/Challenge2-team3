import tempfile
import unittest
from pathlib import Path

from editor.agents import Agents
from editor.review_issues import hard_checks
from editor.workflow import AUTO_ROUNDS, EDITOR_ROUNDS, EditorWorkflow, WorkflowError

STUCK = "demo-stuck"


class HardCheckTest(unittest.TestCase):
    def test_missing_quantity_unit_and_unused(self):
        recipe = {"title": "T", "steps": ["Mehl sieben."], "ingredients": [
            {"name": "Mehl", "amount": 100, "unit": "g"},
            {"name": "Zucker", "amount": None, "unit": ""},
            {"name": "Salz", "amount": None, "unit": ""},        # exempt from the quantity rule
            {"name": "Butter", "amount": 5, "unit": ""}]}
        crit = sorted(i["criterion"] for i in hard_checks(recipe, 0))
        self.assertEqual(crit, ["ingredient_unused", "ingredient_unused", "ingredient_unused",
                                "quantity_missing", "unit_missing"])

    def test_compound_word_counts_as_used(self):
        recipe = {"title": "T", "steps": ["Sirup einrühren."],
                  "ingredients": [{"name": "Agavensirup", "amount": 80, "unit": "g"}]}
        self.assertEqual(hard_checks(recipe, 0), [])


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "audit.jsonl"

    def wf(self, agents=None):
        wf = EditorWorkflow(agents or Agents(), self.log)
        wf.start()
        return wf

    def test_wrong_stage_and_unknown_proposal(self):
        wf = self.wf()
        with self.assertRaises(WorkflowError):
            wf.approve()
        with self.assertRaises(WorkflowError):
            wf.select("nope")

    def test_stub_loop_fixes_hard_issues_then_approval_works(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], "weeknight-friendly")
        self.assertEqual(len(wf.rounds), AUTO_ROUNDS)          # round 1 had issues, round 2 clean
        self.assertTrue(wf.rounds[1]["fixed"])
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        self.assertEqual(wf.stage, "approved")
        self.assertEqual(wf.result["nutrition"][0]["nutrition"]["status"], "pending")

    def test_hard_issues_block_approval_when_never_fixed(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        self.assertLessEqual(len(wf.rounds), AUTO_ROUNDS)
        self.assertFalse(wf.can_approve()[0])
        with self.assertRaises(WorkflowError):
            wf.approve()

    def test_send_back_needs_comment_and_is_limited(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        with self.assertRaises(WorkflowError):
            wf.send_back("  ")
        for _ in range(EDITOR_ROUNDS):
            wf.send_back("fewer ingredients please")
        with self.assertRaises(WorkflowError):
            wf.send_back("one more")

    def test_dismiss_needs_reason_unblocks_and_is_audited(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        for issue in [i for i in wf.issues if i["kind"] == "hard"]:
            with self.assertRaises(WorkflowError):
                wf.dismiss(issue["key"], "")
            wf.dismiss(issue["key"], "step 2 does use it")
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        self.assertTrue(wf.result["approved_with_warnings"])
        self.assertIn("editor_dismissed", self.log.read_text(encoding="utf-8"))

    def test_dismissal_survives_next_round(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        target = next(i for i in wf.issues if i["kind"] == "hard")
        wf.dismiss(target["key"], "false alarm")
        wf.send_back("tweak")
        same = next(i for i in wf.issues if i["key"] == target["key"])
        self.assertEqual(same["status"], "dismissed")

    def test_soft_issue_does_not_block(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], "demo-soft")
        self.assertTrue(any(i["kind"] == "soft" for i in wf.issues))
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        self.assertTrue(wf.result["approved_with_warnings"])

    def test_reject_all_gives_new_topics_and_runs_out_cleanly(self):
        wf = self.wf()
        seen = {p["topic"] for p in wf.proposals}
        wf.reject_all("none fit")
        now = {p["topic"] for p in wf.proposals}
        self.assertFalse(seen & now)
        wf.reject_all()
        with self.assertRaises(WorkflowError):          # pool of 12 topics exhausted
            wf.reject_all()

    def test_agent_crash_retries_once_then_clear_error(self):
        def boom(*a):
            raise RuntimeError("LLM timeout")
        wf = self.wf(Agents(generate=boom))
        with self.assertRaises(WorkflowError) as ctx:
            wf.select(wf.proposals[0]["id"])
        self.assertIn("recipes failed after 2 attempts", str(ctx.exception))
        self.assertEqual(wf.stage, "proposals")           # editor can try again

    def test_malformed_agent_output_is_rejected(self):
        wf = self.wf(Agents(generate=lambda p, n: {"recipes": [{"title": "only one"}]}))
        with self.assertRaises(WorkflowError):
            wf.select(wf.proposals[0]["id"])

    def test_empty_proposals_is_a_clear_error(self):
        with self.assertRaises(WorkflowError):
            EditorWorkflow(Agents(propose=lambda e, n: ([], [])), self.log).start()


if __name__ == "__main__":
    unittest.main()
