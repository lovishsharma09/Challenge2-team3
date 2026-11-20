import tempfile
import unittest
from pathlib import Path

from editor.agents import Agents
from editor.display import archive_summary, wikimedia_summary
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


class MismatchTest(unittest.TestCase):
    def crit(self, ingredients, steps):
        return sorted(i["criterion"] for i in hard_checks({"title": "T", "ingredients": ingredients, "steps": steps}, 0))

    def test_tbsp_tsp_mixup(self):
        self.assertEqual(self.crit([{"name": "Olivenöl", "amount": 2, "unit": "EL"}], ["3 TL Olivenöl erhitzen."]),
                         ["unit_mismatch"])

    def test_steps_exceed_list(self):
        self.assertEqual(self.crit([{"name": "Mehl", "amount": 200, "unit": "g"}],
                                   ["150 g Mehl sieben.", "100 g Mehl unterheben."]), ["quantity_mismatch"])

    def test_split_amounts_within_list_are_fine(self):
        self.assertEqual(self.crit([{"name": "Mehl", "amount": 250, "unit": "g"}],
                                   ["150 g Mehl sieben.", "100 g Mehl unterheben."]), [])

    def test_decimal_comma_and_unrelated_words(self):
        self.assertEqual(self.crit([{"name": "Butter", "amount": 1.5, "unit": "EL"}],
                                   ["1,5 EL Butter schmelzen und 20 Minuten warten."]), [])


class DisplayTest(unittest.TestCase):
    def test_archive_unavailable_is_never_shown_as_no_match(self):
        level, text = archive_summary({"archive": {"match_status": "archive_unavailable", "available": False,
                                                    "similar_recipes": [], "repetition_risk": "unknown"}})
        self.assertEqual(level, "warn")
        self.assertIn("could NOT be checked", text)

    def test_no_match_and_matches_and_legacy_shape(self):
        self.assertIn("no credible match", archive_summary({"archive": {"match_status": "no_match_found",
                                                                         "similar_recipes": [], "repetition_risk": "low"}})[1])
        self.assertIn("Pasta", archive_summary({"archive": {"match_status": "matches_found", "repetition_risk": "high",
                                                             "similar_recipes": [{"title": "Pasta"}]}})[1])
        self.assertIn("no credible match", archive_summary({"archive": {"similar_recipes": [], "repetition_risk": "low"}})[1])
        self.assertEqual(archive_summary({})[0], "warn")          # missing block: unknown risk, warn

    def test_wikimedia_states(self):
        ok = wikimedia_summary({"trend": {"wikimedia": {"status": "available", "article": "Kürbis", "score": 55}}})
        self.assertEqual(ok[0], "ok")
        for st in ("no_article_found", "no_data", "unavailable"):
            level, text = wikimedia_summary({"trend": {"wikimedia": {"status": st, "error": "HTTP 503"}}})
            self.assertEqual(level, "warn")
            self.assertIn("could NOT be checked", text)
        self.assertEqual(wikimedia_summary({"trend": {}})[0], "warn")

    def test_stub_proposals_exercise_the_unavailable_states(self):
        accepted, _ = Agents().propose(set(), 12)
        by = {p["topic"]: p for p in accepted}
        self.assertEqual(archive_summary(by["Haferflocken"])[0], "warn")
        self.assertEqual(wikimedia_summary(by["Rosenkohl"])[0], "warn")


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "audit.jsonl"
        self.cards = Path(tmp.name) / "cards"

    def wf(self, agents=None):
        wf = EditorWorkflow(agents or Agents(), self.log, self.cards)
        wf.start()
        return wf

    def test_wrong_stage_and_unknown_proposal(self):
        wf = self.wf()
        with self.assertRaises(WorkflowError):
            wf.approve()
        with self.assertRaises(WorkflowError):
            wf.select("nope")

    # ---- loop + approval rules
    def test_stub_loop_fixes_hard_issues_then_approval_exports_two_cards(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], "weeknight-friendly")
        self.assertEqual(len(wf.rounds), AUTO_ROUNDS)          # round 1 had issues, round 2 clean
        self.assertTrue(wf.rounds[1]["fixed"])
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        self.assertEqual(wf.stage, "approved")
        self.assertEqual(wf.result["nutrition"][0]["nutrition"]["status"], "pending")
        self.assertEqual(len(wf.result["cards"]), 2)
        self.assertTrue(all(Path(c).is_file() for c in wf.result["cards"]))

    def test_no_cards_are_exported_before_approval(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        self.assertFalse(self.cards.exists() and any(self.cards.iterdir()))

    def test_hard_issues_block_approval_when_never_fixed(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        self.assertLessEqual(len(wf.rounds), AUTO_ROUNDS)
        self.assertFalse(wf.can_approve()[0])
        with self.assertRaises(WorkflowError):
            wf.approve()

    def test_hard_issues_can_not_be_dismissed(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        for issue in [i for i in wf.issues if i["kind"] == "hard"]:
            with self.assertRaises(WorkflowError):
                wf.acknowledge(issue["key"], "I know better")
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

    def test_soft_issue_does_not_block_needs_reason_to_acknowledge_and_survives_rounds(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], "demo-soft")
        soft = next(i for i in wf.issues if i["kind"] == "soft")
        self.assertTrue(wf.can_approve()[0])
        with self.assertRaises(WorkflowError):
            wf.acknowledge(soft["key"], "")
        wf.acknowledge(soft["key"], "title is fine")
        wf.send_back("tweak")
        same = next(i for i in wf.issues if i["key"] == soft["key"])
        self.assertEqual(same["status"], "dismissed")
        wf.approve()
        self.assertTrue(wf.result["approved_with_warnings"])
        self.assertIn("editor_acknowledged_soft", self.log.read_text(encoding="utf-8"))

    # ---- review finding 1: a failed review must never leave an unreviewed draft approvable
    def test_failed_review_after_send_back_keeps_previous_reviewed_draft(self):
        agents = Agents()
        wf = self.wf(agents)
        wf.select(wf.proposals[0]["id"], "demo-soft")
        before_bundle, before_issues, before_rounds = wf.bundle, [dict(i) for i in wf.issues], len(wf.rounds)
        def broken_review(bundle, notes):
            raise RuntimeError("review timeout")
        agents.review = broken_review
        with self.assertRaises(WorkflowError):
            wf.send_back("add more garlic")
        self.assertIs(wf.bundle, before_bundle)                     # old reviewed draft stays
        self.assertEqual(wf.issues, before_issues)
        self.assertEqual(len(wf.rounds), before_rounds)
        self.assertEqual(wf.editor_rounds_left(), EDITOR_ROUNDS)    # the failed attempt is not counted
        self.assertIn("revision_discarded", self.log.read_text(encoding="utf-8"))
        agents.review = Agents().review                             # provider is back: normal flow continues
        wf.send_back("add more garlic")
        self.assertIn("garlic", wf.bundle["recipes"][0]["subtitle"])

    def test_failed_revision_also_keeps_previous_draft(self):
        agents = Agents()
        wf = self.wf(agents)
        wf.select(wf.proposals[0]["id"], "demo-soft")
        before = wf.bundle
        def broken(*a):
            raise RuntimeError("down")
        agents.revise = broken
        with self.assertRaises(WorkflowError):
            wf.send_back("x")
        self.assertIs(wf.bundle, before)

    def test_first_review_failure_leaves_a_clean_state(self):
        def broken(bundle, notes):
            raise RuntimeError("down")
        wf = self.wf(Agents(review=broken))
        with self.assertRaises(WorkflowError):
            wf.select(wf.proposals[0]["id"])
        self.assertEqual((wf.stage, wf.bundle, wf.issues, wf.rounds), ("proposals", None, [], []))

    def test_auto_revision_failure_still_reaches_review_with_notice_and_blocks(self):
        def broken(*a):
            raise RuntimeError("down")
        wf = self.wf(Agents(revise=broken))
        wf.select(wf.proposals[0]["id"])                            # stub recipes have hard issues
        self.assertEqual(wf.stage, "review")
        self.assertTrue(wf.notices)
        self.assertFalse(wf.can_approve()[0])

    def test_discard_is_the_way_out_of_a_dead_end(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], STUCK)
        wf.discard("nothing works")
        self.assertEqual((wf.stage, wf.bundle, wf.selected), ("proposals", None, None))
        wf.select(wf.proposals[1]["id"], "")
        self.assertEqual(wf.stage, "review")
        self.assertIn("editor_discarded_recipes", self.log.read_text(encoding="utf-8"))

    # ---- offline end-to-end: select -> review two drafts -> approve with soft warning -> two HTML cards
    def test_end_to_end_with_soft_warning_produces_two_cards(self):
        wf = self.wf()
        wf.select(wf.proposals[0]["id"], "weeknight-friendly demo-soft")
        self.assertEqual(len(wf.bundle["recipes"]), 2)
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        cards = [Path(c) for c in wf.result["cards"]]
        self.assertEqual(len(cards), 2)
        for card, recipe in zip(cards, wf.bundle["recipes"]):
            page = card.read_text(encoding="utf-8")
            self.assertIn("MOCK-Entwurf · kein echtes Rezept", page)              # the stub is active: never claim "AI-generated"
            self.assertNotIn("KI-generierter Rezeptentwurf", page)
            self.assertIn(recipe["title"], page)
        warned = next(i for i in wf.result["approved_with_warnings"])
        self.assertEqual(warned["recipe_index"], 0)             # the soft finding concerns recipe 1 only
        self.assertIn("Redaktionell freigegeben mit offenen Prüfhinweisen", cards[0].read_text(encoding="utf-8"))
        self.assertNotIn("Redaktionell freigegeben", cards[1].read_text(encoding="utf-8"))

    def test_reject_all_gives_new_topics_and_runs_out_cleanly(self):
        wf = self.wf()
        seen = {p["topic"] for p in wf.proposals}
        wf.reject_all("none fit")
        self.assertFalse(seen & {p["topic"] for p in wf.proposals})
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

    def test_progress_messages_are_reported_in_order_including_retries(self):
        calls = {"n": 0}
        def flaky(prop, notes):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("timeout")
            return Agents().generate(prop, notes)
        wf = self.wf(Agents(generate=flaky))
        seen = []
        wf.on_progress = seen.append
        wf.select(wf.proposals[0]["id"])
        self.assertEqual(seen[:3], ["Generating two recipes…", "Generating two recipes… (retry 1)",
                                    "Reviewing the recipes…"])
        self.assertIn("Revising the recipes…", seen)

    def test_empty_proposals_is_a_clear_error(self):
        with self.assertRaises(WorkflowError):
            EditorWorkflow(Agents(propose=lambda e, n: ([], [])), self.log, self.cards).start()


if __name__ == "__main__":
    unittest.main()
