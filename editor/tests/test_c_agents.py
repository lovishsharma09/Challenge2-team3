"""Person C's pipeline behind our workflow. Everything here is OFFLINE: C's mock client and its synthetic nutrition fixture, no network, no keys."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from editor import c_agents as C
from editor.agents import Agents
from editor.batch import load_batch, propose_from_batch
from editor.review_issues import hard_checks, review_all
from editor.tests.fixtures import sample_batch, write_batch
from editor.workflow import EditorWorkflow

HAVE_C = (C.C_SRC / "c_pipeline").is_dir()


def c_recipe(**kw):
    r = {"id": "r1", "proposal_id": "p1", "variant": "A", "version": 1, "ai_generated": True, "title": "Grünkohl-Eintopf",
         "intro": "Ein Klassiker für kalte Tage.", "servings": {"amount": 4.0, "unit": "Portionen"},
         "times": {"prep_min": 20.0, "cook_min": 35.0, "rest_min": None},
         "ingredients": [{"id": "i1", "group": None, "name": "Grünkohl", "quantity": 500.0, "unit": "g", "note": "geputzt"},
                         {"id": "i2", "group": None, "name": "Zwiebeln", "quantity": 2.0, "unit": None, "note": None},
                         {"id": "i3", "group": None, "name": "Salz", "quantity": None, "unit": None, "note": None}],
         "steps": [{"group": None, "text": "Grünkohl waschen.", "uses": ["i1"], "temperature_c": None, "duration_min": None},
                   {"group": None, "text": "Zwiebeln und Salz zugeben.", "uses": ["i2", "i3"], "temperature_c": None, "duration_min": 25.0}],
         "serving_tip": "Dazu Roggenbrot."}
    r.update(kw)
    return r


class ShapeTest(unittest.TestCase):
    def test_pitch_for_c_carries_only_the_pitchs_own_text_never_archive_data(self):
        p = sample_batch()["proposals"][0]
        p["archive"]["similar_recipes"] = [{"title": "SECRET-ARCHIVE-TITLE", "category": "Suppen", "published": "2020-08-01"}]
        c = C.proposal_to_c(p)
        text = json.dumps(c, ensure_ascii=False)
        self.assertNotIn("SECRET-ARCHIVE-TITLE", text)
        self.assertNotIn("2020-08", text)
        self.assertNotIn("archive", c)
        self.assertEqual(c["title"], p["title"])
        self.assertEqual(c["recipe_ideas"], p["recipe_ideas"])
        self.assertEqual(c["why_now"], p["trend"]["why_relevant"])
        self.assertEqual(c["brand_fit_summary"], p["brand_fit"]["reasoning"])
        self.assertEqual(C.proposal_to_c({"id": "x", "trend": "odd", "brand_fit": None})["why_now"], None)    # odd shapes never crash

    def test_c_recipe_becomes_our_recipe_and_keeps_the_original(self):
        c = c_recipe()
        before = copy.deepcopy(c)
        o = C.to_ours(c, mock=True)
        self.assertEqual(c, before)                                                   # the source is not modified
        self.assertEqual((o["title"], o["subtitle"], o["servings"]), ("Grünkohl-Eintopf", "Ein Klassiker für kalte Tage.", 4))
        self.assertEqual((o["prep_time_minutes"], o["cook_time_minutes"]), (20, 35))
        self.assertEqual(o["steps"], ["Grünkohl waschen.", "Zwiebeln und Salz zugeben."])
        self.assertEqual([(i["amount"], i["unit"], i["name"]) for i in o["ingredients"]],
                         [(500, "g", "Grünkohl (geputzt)"), (2, "", "Zwiebeln"), (None, "", "Salz")])
        self.assertEqual([i["countable"] for i in o["ingredients"]], [False, True, False])
        self.assertTrue(o["mock"])
        self.assertEqual(o["_c"], before)                                             # Person C's object travels along, unchanged
        self.assertIsNot(o["_c"], c)
        self.assertFalse(C.to_ours(c, mock=False)["mock"])

    def test_counted_items_need_no_unit_but_a_measure_without_unit_is_still_a_hard_issue(self):
        o = C.to_ours(c_recipe(), mock=False)
        self.assertEqual([i for i in hard_checks(o, 0) if i["criterion"] == "unit_missing"], [])       # "2 Zwiebeln" is fine
        bad = copy.deepcopy(o)
        bad["ingredients"].append({"name": "Mehl", "amount": 250, "unit": ""})                          # not countable: needs a unit
        self.assertEqual([i["criterion"] for i in hard_checks(bad, 0) if "Mehl" in i["message"] and i["criterion"] == "unit_missing"], ["unit_missing"])

    def test_nutrition_is_never_invented(self):
        self.assertEqual(C.nutrition_to_ours(None, False)["status"], "pending")
        self.assertEqual(C.nutrition_to_ours({"per_serving": {"kcal": None}}, False)["status"], "pending")
        gaps = C.nutrition_to_ours({"per_serving": {"kcal": None}, "unmatched": [{"original": "80 g Gouda", "reason": "?"}]}, True)
        self.assertEqual((gaps["status"], gaps["per_serving"], gaps["unmatched"], gaps["synthetic"]), ("pending", None, ["80 g Gouda"], True))
        n = {"per_serving": {"kcal": 535, "fat_g": 30}, "coverage": {"quality": "hoch", "ingredients_calculated": 9, "ingredients_needing_calc": 10},
             "ingredients": [{"original": "1 Zwiebel", "db_name": "Zwiebel, roh", "confidence": 0.6, "assumption": True},
                             {"original": "500 g Kohl", "db_name": "Kohl", "confidence": 0.9, "assumption": False}],
             "unmatched": [{"original": "80 g Gouda"}]}
        o = C.nutrition_to_ours(n, True)
        self.assertEqual((o["status"], o["synthetic"]), ("ok", True))
        self.assertEqual(o["assumptions"], [{"original": "1 Zwiebel", "used": "Zwiebel, roh", "confidence": 0.6}])
        self.assertEqual(o["unmatched"], ["80 g Gouda"])
        self.assertIn("Qualität: hoch (9 von 10 Zutaten)", o["coverage_text"])

    def test_review_findings_code_errors_are_hard_llm_remarks_are_soft(self):
        rv = {"criteria": {
            "all_ingredients_used": {"pass": False, "issues": ["Zutat wird in keinem Schritt verwendet: Lorbeer", "[LLM] Salz wird nicht erwähnt"]},
            "units_consistent": {"pass": False, "issues": ["Butter: Schritte 30 g, Liste 20 g", "Hinweis: Mengenangabe prüfen"]},
            "title": {"pass": True, "issues": ["[LLM] Titel ist okay"]},
            "tbsp_tsp": {"pass": True, "issues": ["Hinweis: 1 EL Zimt wirkt viel"]}},
            "extras": {"brand_fit": {"pass": False, "issues": ["[LLM] zu exotisch"]}}}
        f = C.findings_from_review(rv, 1)
        by = [(x["criterion"], x["kind"], x["family"], x["message"]) for x in f]
        self.assertIn(("all_ingredients_used", "hard", "unused", "Zutat wird in keinem Schritt verwendet: Lorbeer"), by)
        self.assertIn(("all_ingredients_used", "soft", "", "Salz wird nicht erwähnt"), by)
        self.assertIn(("units_consistent", "soft", "", "Butter: Schritte 30 g, Liste 20 g"), by)      # free-text arithmetic is a heuristic: soft
        self.assertIn(("units_consistent", "soft", "", "Mengenangabe prüfen"), by)
        self.assertIn(("tbsp_tsp", "soft", "", "1 EL Zimt wirkt viel"), by)                   # a warning is kept even on a passing criterion
        self.assertIn(("brand_fit", "soft", "", "zu exotisch"), by)
        self.assertFalse(any(x[3] == "Titel ist okay" for x in by))                           # an LLM remark on a PASSING criterion is dropped
        self.assertTrue(all(x["recipe_index"] == 1 for x in f))

    def test_only_data_level_code_errors_block_approval(self):
        """Found in a live run: text-parsing findings (units, spoon sizes, plausibility, order) must never be hard."""
        crit = {k: {"pass": False, "issues": [f"{k}: Befund"]} for k in
                ("quantity_completeness", "all_ingredients_used", "units_consistent", "tbsp_tsp", "quantity_plausibility", "step_order")}
        kinds = {f["criterion"]: f["kind"] for f in C.findings_from_review({"criteria": crit, "extras": {}}, 0)}
        self.assertEqual(kinds, {"quantity_completeness": "hard", "all_ingredients_used": "hard", "units_consistent": "soft",
                                 "tbsp_tsp": "soft", "quantity_plausibility": "soft", "step_order": "soft"})

    def test_llm_false_alarm_remarks_are_dropped_and_soft_noise_is_capped_and_deduplicated(self):
        issues = (["Brühe: Einheit im Schritt (g) weicht von der Liste (ml) ab"] * 3 +                  # duplicates collapse to one
                  ["[LLM] Die Code-Hinweise sind Fehlalarme: Schritt 1 nennt 600 g", "[LLM] Der Senf ist korrekt hochgerechnet",
                   "[LLM] Das ist kein Fehler", "[LLM] Die Reihenfolge der Zutaten ist ungewöhnlich", "[LLM] Zu viel Fett für die Marke",
                   "[LLM] Garzeit zu kurz", "[LLM] Salz fehlt im Rezept"])
        rv = {"criteria": {"units_consistent": {"pass": False, "issues": issues, "fix": "x"}}, "extras": {}}
        out = C.findings_from_review(rv, 0)
        msgs = [f["message"] for f in out]
        self.assertEqual(sum("Einheit im Schritt" in m for m in msgs), 1)
        self.assertFalse(any("Fehlalarm" in m or "korrekt hochgerechnet" in m or "kein Fehler" in m for m in msgs))
        self.assertLessEqual(len(out), C.MAX_SOFT_PER_CRITERION)                                       # capped per criterion

    def test_llm_confirmations_are_not_issues(self):
        """From a live run: 'Alle übrigen Mengen stimmen zwischen Liste und Schritten überein' was shown as a warning."""
        confirmations = ["Alle übrigen Mengen stimmen zwischen Liste und Schritten überein (80 g Speck, 2 Zwiebeln).",
                         "Die Mengen stimmen überein", "Keine weiteren Probleme gefunden", "Keine Abweichungen zwischen Liste und Text",
                         "Die Übereinstimmung von Liste und Schritten ist gegeben"]
        real = ["Der Senf fehlt in Schritt 3", "Mengen stimmen nicht zwischen Liste und Schritten"]
        rv = {"criteria": {"units_consistent": {"pass": False, "fix": "x", "issues": [f"[LLM] {m}" for m in confirmations + real]}}, "extras": {}}
        msgs = [f["message"] for f in C.findings_from_review(rv, 0)]
        self.assertFalse(any("überein" in m.lower() and "nicht" not in m.lower() for m in msgs), msgs)
        self.assertFalse(any(m.startswith("Keine") for m in msgs), msgs)
        self.assertIn("Der Senf fehlt in Schritt 3", msgs)                                           # a real complaint survives

    def test_the_same_problem_is_reported_once_when_both_checkers_find_it(self):
        class FakeAgents:
            def review(self, bundle, notes):
                return [{"recipe_index": 0, "criterion": "all_ingredients_used", "message": "C: Lorbeer unbenutzt", "kind": "hard", "family": "unused"},
                        {"recipe_index": 0, "criterion": "step_order", "message": "C: Reihenfolge", "kind": "hard", "family": ""},
                        {"recipe_index": 1, "criterion": "all_ingredients_used", "message": "C: anderes Rezept", "kind": "hard", "family": "unused"}]
        o = C.to_ours(c_recipe(), False)
        o["ingredients"].append({"name": "Lorbeer", "amount": 1, "unit": "Blatt"})            # ours finds this unused in recipe 0
        issues = review_all(FakeAgents(), {"recipes": [o, copy.deepcopy(o)]}, "")
        msgs = [i["message"] for i in issues]
        self.assertFalse(any("C: Lorbeer unbenutzt" in m for m in msgs))                       # duplicate of our own finding: dropped
        self.assertTrue(any("C: Reihenfolge" in m for m in msgs))                              # no family: kept
        self.assertTrue(any("C: anderes Rezept" in m for m in msgs) or any("Lorbeer" in m for m in msgs))


@unittest.skipUnless(HAVE_C, "person_c not present (merge main)")
class OfflineEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = C.CAgents("mock")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def workflow(self):
        batch = load_batch(write_batch(self.dir))
        wf = EditorWorkflow(self.engine.agents(Agents(propose=propose_from_batch(batch))), self.dir / "audit.jsonl", self.dir / "cards")
        wf.start()
        return wf

    def test_generate_gives_two_recipes_in_our_shape_flagged_mock(self):
        b = self.engine.generate(sample_batch()["proposals"][0], "weeknight-friendly")
        self.assertEqual(len(b["recipes"]), 2)
        for r in b["recipes"]:
            self.assertTrue(r["mock"])
            self.assertTrue(r["steps"] and all(isinstance(s, str) for s in r["steps"]))
            self.assertIn("_c", r)
        self.assertEqual(b["steering_notes"], "weeknight-friendly")

    def test_no_archive_titles_reach_any_prompt(self):
        prompts, original = [], self.engine.client.chat_json
        def spy(system, user, **kw):
            prompts.append(user)
            return original(system, user, **kw)
        p = sample_batch()["proposals"][0]
        p["archive"]["similar_recipes"] = [{"title": "SECRET-ARCHIVE-TITLE"}]
        self.engine.client.chat_json = spy
        try:
            bundle = self.engine.generate(p, "")
            self.engine.review(bundle, "")
        finally:
            self.engine.client.chat_json = original
        self.assertTrue(prompts)
        self.assertFalse(any("SECRET-ARCHIVE-TITLE" in x for x in prompts))
        self.assertTrue(any("(archive not available)" in x for x in prompts))                  # C's own placeholder: no archive was offered
        self.assertTrue(any(p["recipe_ideas"][0] in x for x in prompts))                       # the pitch's own text is what generation gets

    def test_end_to_end_through_our_workflow_review_blocks_then_revision_fixes_then_cards(self):
        wf = self.workflow()
        wf.select("proposal-pastinake", "weeknight-friendly")
        self.assertEqual(wf.stage, "review")
        first = [i for i in wf.rounds[0]["issues"] if i["status"] == "open"]
        self.assertTrue(any(i["kind"] == "hard" for i in first))                               # the planted defect is found by code
        self.assertTrue(any(i["criterion"] == "all_ingredients_used" and i["kind"] == "hard" for i in first))   # Person C's check counts as hard
        self.assertEqual(len(wf.rounds), 2)
        self.assertEqual([i["status"] for i in wf.rounds[1]["issues"] if i["kind"] == "hard"], [])
        self.assertTrue(wf.rounds[1]["changes"])                                                # what the revision changed is recorded
        self.assertTrue(wf.can_approve()[0])
        wf.approve()
        self.assertEqual(len(wf.result["cards"]), 2)
        pages = [Path(c).read_text(encoding="utf-8") for c in wf.result["cards"]]
        for page in pages:
            self.assertIn("MOCK-Entwurf", page)                                                 # still a mock draft: labelled as such
            self.assertNotIn("KI-generierter Rezeptentwurf", page)
        self.assertIn("TESTDATEN", pages[0])                                                    # synthetic nutrition says so on the card
        nut = [n["nutrition"] for n in wf.result["nutrition"]]
        self.assertEqual((nut[0]["status"], nut[0]["synthetic"]), ("ok", True))
        self.assertEqual(nut[1]["status"], "pending")                                            # an unmatched ingredient: nothing is invented
        self.assertIn("Gouda", " ".join(nut[1]["unmatched"]))
        self.assertTrue((self.dir / "cards" / "pastinake-1-naehrwerte.json").is_file())          # the complete record is kept next to the card

    def test_our_rules_still_govern_hard_issues_never_dismissable(self):
        wf = self.workflow()
        wf.select("proposal-pastinake", "")
        # make a hard issue appear again and check it cannot be dismissed
        wf.issues.append({"key": "x", "recipe_index": 0, "criterion": "all_ingredients_used", "kind": "hard", "message": "m",
                          "status": "open", "dismiss_reason": "", "family": "unused"})
        self.assertFalse(wf.can_approve()[0])
        with self.assertRaises(Exception):
            wf.acknowledge("x", "I know better")

    def test_mirrored_differentiation_findings_are_reported_once(self):
        rv = {"criteria": {}, "extras": {"differentiation": {"pass": False, "fix": "x", "issues": ["Zutaten überschneiden sich zu 69% mit dem Schwesterrezept"]}}}
        bundle = self.engine.generate(sample_batch()["proposals"][0], "")
        with mock.patch.object(self.engine._review_agent, "review_recipe", lambda *a, **k: copy.deepcopy(rv)):
            findings = self.engine.review(bundle, "")
        self.assertEqual([f["criterion"] for f in findings].count("differentiation"), 1)

    def test_editor_comment_goes_to_the_recipe_agent_and_a_missing_mock_fixture_is_tolerated(self):
        wf = self.workflow()
        wf.select("proposal-pastinake", "")
        seen = []
        original = self.engine._recipe_agent.revise_recipe
        def spy(client, recipe, report, editor_comment, steering):
            seen.append((recipe["id"], editor_comment))
            return original(client, recipe, report, editor_comment, steering)
        with mock.patch.object(self.engine._recipe_agent, "revise_recipe", spy):
            wf.send_back("weniger Sahne, alltagstauglicher")
        self.assertEqual({i for i, _c in seen}, {"r1", "r2"})                                    # an editor comment applies to both recipes
        self.assertTrue(all(c == "weniger Sahne, alltagstauglicher" for _i, c in seen))
        self.assertEqual(wf.editor_rounds_left(), 1)                                             # r2 has no mock fixture: tolerated, not a failure


class ImageChecksOffTest(unittest.TestCase):
    """Found in a live run: C's strict image-prompt checks rejected every first reply (20-45 s lost each time) for output we never use."""

    class FakeClient:
        def __init__(self):
            self.seen = []

        def chat_json(self, system, user, *, validate=None, retries=2, temperature=0.4):
            self.seen.append(validate)
            return {"ok": True}

        def ping(self):
            return "pong"

    def test_only_image_problems_are_filtered_everything_else_is_kept(self):
        fake = self.FakeClient()
        wrapped = C.ImageChecksOff(fake)
        wrapped.chat_json("s", "u", validate=lambda o: ["recipe 1: image_prompt: mentions 'gravy'", "recipe 1: image_components: 'x' is not visible",
                                                         "recipe 1: ingredients[2].quantity must be a number", "recipe 2: steps are empty"])
        self.assertEqual(fake.seen[0](None), ["recipe 1: ingredients[2].quantity must be a number", "recipe 2: steps are empty"])

    def test_without_a_validator_nothing_changes_and_other_attributes_pass_through(self):
        fake = self.FakeClient()
        wrapped = C.ImageChecksOff(fake)
        self.assertEqual(wrapped.chat_json("s", "u"), {"ok": True})
        self.assertIsNone(fake.seen[0])
        self.assertEqual(wrapped.ping(), "pong")

    @unittest.skipUnless(HAVE_C, "person_c not present")
    def test_the_engine_wraps_its_clients(self):
        e = C.CAgents("mock")
        self.assertIsInstance(e.client, C.ImageChecksOff)
        self.assertIsInstance(e.client_review, C.ImageChecksOff)


class ConfigurationTest(unittest.TestCase):
    def test_missing_package_is_a_clear_error_not_a_silent_fallback(self):
        with mock.patch.object(C, "C_SRC", Path("/nonexistent/person_c/src")):
            with self.assertRaises(C.CUnavailable) as ctx:
                C.CAgents("mock")
        self.assertIn("Merge main", str(ctx.exception))

    @unittest.skipUnless(HAVE_C, "person_c not present")
    def test_live_mode_needs_gateway_settings_and_builds_no_connection_in_tests(self):
        with mock.patch.object(C, "_env", lambda name: ""):
            with self.assertRaises(C.CUnavailable) as ctx:
                C.CAgents("live")
        self.assertIn("TESSERACTED_BASE_URL", str(ctx.exception))
        env = {"TESSERACTED_BASE_URL": "http://gateway.invalid/ai_gateway", "TESSERACTED_API_KEY": "sk-FAKE", "EDITOR_LLM_MODEL": "m"}
        with mock.patch.object(C, "_env", lambda name: env.get(name, "")):
            engine = C.CAgents("live")                               # constructing must not touch the network
        self.assertFalse(engine.mock)
        self.assertEqual(type(engine.client._client).__name__, "OpenAICompatClient")
        self.assertIn(engine.db.is_fixture, (False,))                 # live mode uses the REAL nutrition CSV, never the synthetic fixture
        self.assertEqual(len(engine.db.entries) > 1000, True)

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            C.CAgents("turbo")


if __name__ == "__main__":
    unittest.main()
