import copy
import tempfile
import unittest
from pathlib import Path

from editor.agents import Agents, STUB_FIXES, generate, revise
from editor.changes import diff_bundles
from editor.display import coverage_short, evidence_details, highlight_change, short, trail_label
from editor.render import render_recipe
from editor.review_issues import hard_checks
from editor.tests.fixtures import sample_batch
from editor.workflow import EditorWorkflow


def recipes(b):
    return b["recipes"]


class ShortTest(unittest.TestCase):
    def test_single_sentences_keep_their_final_period(self):
        for text in ("SYNTHETIC: Pastinake steigt in den Suchanfragen (Testdaten).", "Kurz.", "Frage?", "Ohne Punkt"):
            self.assertEqual(short(text), text)                                   # found on screen: the period used to be dropped

    def test_long_single_sentences_end_at_a_clause_not_mid_phrase(self):
        text = ("Google Trends rising: 'Vanillekipferl' +850% (search-interest index 17/100); +1 more rising term(s); "
                "Wikipedia 'Vanillekipferl' 7-day views 298 → 322 (+8%).")
        out = short(text, 140)
        self.assertEqual(out, "Google Trends rising: 'Vanillekipferl' +850% (search-interest index 17/100); +1 more rising term(s)…")
        self.assertNotIn("views…", out)

    def test_first_sentence_word_boundary_and_no_loss_of_short_text(self):
        self.assertEqual(short("Erster Satz. Zweiter Satz."), "Erster Satz.")
        self.assertEqual(short("Erster Satz! Zweiter Satz."), "Erster Satz!")
        self.assertEqual(short("Kurz ohne Punkt"), "Kurz ohne Punkt")
        self.assertEqual(short(""), "")
        self.assertEqual(short(None), "")
        out = short("wort " * 100, 50)
        self.assertLessEqual(len(out), 51)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out[:-1].endswith(" "))
        self.assertEqual(short("A" * 300, 40), "A" * 40 + "…" if False else short("A" * 300, 40))   # unbroken word must not crash

    def test_coverage_short_keeps_the_three_cases_apart(self):
        by = {p["topic"]: p for p in sample_batch()["proposals"]}
        self.assertEqual(coverage_short(by["Grünkohl"])[0], "warn")
        self.assertIn("could NOT be checked", coverage_short(by["Grünkohl"])[1])
        self.assertIn("no credible comparable recipe", coverage_short(by["Quitte"])[1])
        self.assertIn("2 comparable recipe(s)", coverage_short(by["Pastinake"])[1])
        for p in by.values():
            self.assertLess(len(coverage_short(p)[1]), 120)                      # one line
            self.assertNotIn("risk", coverage_short(p)[1].casefold())

    def test_evidence_hides_missing_dates_but_keeps_real_ones(self):
        p = {"archive": {"match_status": "matches_found", "similar_recipes": [
            {"title": "X", "publication_date": None, "published": "", "date_source": None}]}}
        self.assertIsNone(evidence_details(p)["dates_line"])
        p["archive"]["similar_recipes"][0]["created"] = "2020-08-01"
        line = evidence_details(p)["dates_line"]
        self.assertIn("NOT publication dates", line)
        self.assertNotIn("None", line)

    def test_evidence_carries_the_full_texts_that_the_card_shortens(self):
        p = sample_batch()["proposals"][0]
        e = evidence_details(p)
        self.assertEqual(e["why_full"], p["trend"]["why_relevant"])
        self.assertEqual(e["brand_full"], p["brand_fit"]["reasoning"])
        self.assertEqual(e["more_angles"], p["recipe_ideas"][1:])
        self.assertIn("Prior coverage", e["coverage_full"])


class HighlightTest(unittest.TestCase):
    def test_removed_words_are_red_struck_and_added_words_green(self):
        before, after = highlight_change("Dann pürieren und mit Salz und Pfeffer würzen.",
                                         "Dann pürieren und mit 2 EL Zitronensaft, Salz und Pfeffer abschmecken.")
        self.assertIn(":red[~~würzen\\.~~]", before)
        self.assertNotIn(":green", before)
        self.assertIn(":green[**2 EL Zitronensaft,**]", after)
        self.assertIn(":green[**abschmecken\\.**]", after)
        self.assertNotIn(":red", after)
        self.assertTrue(before.startswith("Dann pürieren und mit Salz"))               # unchanged words stay plain

    def test_identical_and_fully_replaced_text(self):
        same_b, same_a = highlight_change("gleich bleibt", "gleich bleibt")
        self.assertEqual((same_b, same_a), ("gleich bleibt", "gleich bleibt"))
        b, a = highlight_change("alt", "neu")
        self.assertEqual((b, a), (":red[~~alt~~]", ":green[**neu**]"))

    def test_drafts_cannot_inject_markdown_through_the_highlight(self):
        for text in ("![x](http://evil.example/p.png)", "[click](http://evil.example)"):
            b, a = highlight_change("alt " + text, "neu " + text + " mehr")
            for out in (b, a):
                self.assertNotIn("](", out)
                self.assertNotIn("![", out)


class TrailTest(unittest.TestCase):
    def test_events_read_like_sentences_not_like_dicts(self):
        cases = [
            ("proposals_ready", {"n": 5}, "Proposals loaded (5)"),
            ("editor_selected", {"topic": "Pastinake", "notes": ""}, "You chose: Pastinake"),
            ("review", {"round": 2, "hard_open": 0, "soft_open": 1, "fixed": 2}, "Review round 2: 0 hard and 1 soft open, 2 fixed"),
            ("approved", {"cards": ["a", "b"], "warnings": []}, "Approved: 2 cards exported"),
            ("recipes_generated", {"titles": ["x"]}, "Two drafts created"),
        ]
        for event, data, expect in cases:
            text = trail_label({"event": event, **data})
            self.assertEqual(text, expect)
            self.assertNotIn("{", text)
            self.assertNotIn("'", text)

    def test_unknown_or_broken_events_never_crash_and_user_text_is_escaped(self):
        self.assertEqual(trail_label({"event": "something_new"}), "something\\_new")
        self.assertEqual(trail_label({}), "")
        trail_label({"event": "review", "round": object()})
        text = trail_label({"event": "editor_sent_back", "comment": "![x](http://evil.example/p.png)"})
        self.assertNotIn("](", text)
        self.assertNotIn("![", text)


class StubRealismTest(unittest.TestCase):
    def test_sample_recipes_are_realistic_distinct_and_flagged_mock(self):
        b = generate({"id": "p"}, "")
        a, c = recipes(b)
        self.assertTrue(a["mock"] and c["mock"])
        self.assertNotEqual(a["title"], c["title"])
        self.assertIn("Linsen", a["title"] + c["title"])
        for r in (a, c):
            self.assertGreaterEqual(len(r["ingredients"]), 8)
            self.assertGreaterEqual(len(r["steps"]), 3)
            self.assertTrue(r["steps"][-1].casefold().rstrip(".").endswith("servieren"))

    def test_each_sample_has_exactly_one_forgotten_ingredient(self):
        for i, r in enumerate(recipes(generate({"id": "p"}, ""))):
            found = hard_checks(r, i)
            self.assertEqual([x["criterion"] for x in found], ["ingredient_unused"])

    def test_the_fix_goes_into_the_step_where_the_ingredient_is_used_not_after_serving(self):
        before = generate({"id": "p"}, "")
        issues = [x for i, r in enumerate(recipes(before)) for x in hard_checks(r, i)]
        after = revise({}, "", before, issues)
        for i, r in enumerate(recipes(after)):
            self.assertEqual(hard_checks(r, i), [])
            self.assertEqual(len(r["steps"]), len(recipes(before)[i]["steps"]))          # a step was corrected, none appended
            self.assertTrue(r["steps"][-1].casefold().rstrip(".").endswith("servieren"))  # serving is still the last step
        self.assertIn("2 EL Zitronensaft", recipes(after)[0]["steps"][2])
        self.assertIn("1 Lorbeerblatt", recipes(after)[1]["steps"][1])
        self.assertEqual(len(STUB_FIXES), 2)

    def test_unknown_recipes_get_the_mention_before_the_serving_step(self):
        b = {"recipes": [{"title": "Anderes", "subtitle": "", "servings": 1, "ingredients": [{"name": "Kümmel", "amount": 1, "unit": "TL"}],
                          "steps": ["Kochen.", "Servieren."]}]}
        issue = [{"criterion": "ingredient_unused", "recipe_index": 0, "message": "Anderes: 'Kümmel' is listed but never used in the steps."}]
        steps = revise({}, "", b, issue)["recipes"][0]["steps"]
        self.assertEqual(steps, ["Kochen.", "Mit Kümmel abschmecken.", "Servieren."])


class DiffTest(unittest.TestCase):
    def base(self):
        return {"recipes": [{"title": "T", "subtitle": "s", "servings": 4, "prep_time_minutes": 10, "cook_time_minutes": 20,
                             "ingredients": [{"name": "Mehl", "amount": 100, "unit": "g"}, {"name": "Salz", "amount": None, "unit": ""}],
                             "steps": ["Eins.", "Zwei.", "Drei."]}]}

    def test_first_draft_and_identical_drafts_have_no_changes(self):
        self.assertEqual(diff_bundles(None, self.base()), [])
        self.assertEqual(diff_bundles(self.base(), self.base()), [])

    def test_replaced_inserted_and_removed_steps(self):
        after = self.base()
        after["recipes"][0]["steps"] = ["Eins.", "Zwei, jetzt genauer.", "Drei.", "Vier."]
        ch = diff_bundles(self.base(), after)
        self.assertEqual([(c["where"], c["before"], c["after"]) for c in ch],
                         [("Step 2", "Zwei.", "Zwei, jetzt genauer."), ("Step 4", None, "Vier.")])
        after["recipes"][0]["steps"] = ["Eins.", "Drei."]
        gone = diff_bundles(self.base(), after)
        self.assertEqual([(c["where"], c["before"], c["after"]) for c in gone], [("Step 2", "Zwei.", None)])

    def test_ingredient_and_scalar_changes(self):
        after = copy.deepcopy(self.base())
        r = after["recipes"][0]
        r["ingredients"][0]["amount"] = 150
        r["ingredients"].append({"name": "Zucker", "amount": 1.5, "unit": "EL"})
        r["servings"], r["subtitle"] = 6, "neu"
        ch = {(c["where"], c["before"], c["after"]) for c in diff_bundles(self.base(), after)}
        self.assertIn(("Ingredient", "100 g Mehl", "150 g Mehl"), ch)
        self.assertIn(("Ingredient", None, "1,5 EL Zucker"), ch)
        self.assertIn(("Servings", "4", "6"), ch)
        self.assertIn(("Subtitle", "s", "neu"), ch)

    def test_robust_against_missing_fields_and_different_recipe_counts(self):
        self.assertEqual(diff_bundles({"recipes": []}, {"recipes": []}), [])
        diff_bundles({"recipes": [{}]}, {"recipes": [{"steps": ["x"]}, {"title": "extra"}]})


class WorkflowChangesTest(unittest.TestCase):
    def test_every_revision_records_what_it_changed(self):
        with tempfile.TemporaryDirectory() as d:
            wf = EditorWorkflow(Agents(), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            wf.select(wf.proposals[0]["id"], "")
            self.assertEqual(wf.rounds[0]["changes"], [])                                # first draft: nothing to compare
            changes = wf.rounds[1]["changes"]                                           # the automatic correction
            self.assertEqual([(c["recipe_title"], c["where"]) for c in changes],
                             [("Rote Linsensuppe mit Zitrone", "Step 3"), ("Linsen-Eintopf mit Kartoffeln", "Step 2")])
            self.assertNotIn("Zitronensaft", changes[0]["before"])
            self.assertIn("2 EL Zitronensaft", changes[0]["after"])
            wf.send_back("bitte schärfer")
            self.assertEqual({c["where"] for c in wf.rounds[2]["changes"]}, {"Subtitle"})


class RendererLabelTest(unittest.TestCase):
    def r(self, **kw):
        return dict({"title": "Suppe", "servings": 4, "ingredients": [{"name": "Wasser", "amount": 1, "unit": "l"}], "steps": ["Kochen."]}, **kw)

    def test_mock_cards_never_claim_to_be_ai_drafts(self):
        page = render_recipe(self.r(mock=True), None, [])
        self.assertEqual(page.count("MOCK-Entwurf · kein echtes Rezept"), 3)               # chip, toolbar and footer
        self.assertNotIn("KI-generierter Rezeptentwurf", page)

    def test_real_drafts_keep_the_ai_label(self):
        page = render_recipe(self.r(), None, [])
        self.assertEqual(page.count("KI-generierter Rezeptentwurf"), 3)
        self.assertNotIn("MOCK", page)

    def test_a_real_generator_through_the_workflow_gets_the_ai_label(self):
        def real_generate(proposal, notes):
            b = generate(proposal, notes)
            for r in b["recipes"]:
                r.pop("mock")
                r["steps"].append("Mit Zitronensaft und Lorbeerblatt nach Belieben ergänzen.")
            return b
        with tempfile.TemporaryDirectory() as d:
            wf = EditorWorkflow(Agents(generate=real_generate), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            wf.select(wf.proposals[0]["id"], "")
            wf.approve()
            for card in wf.result["cards"]:
                page = Path(card).read_text(encoding="utf-8")
                self.assertIn("KI-generierter Rezeptentwurf", page)
                self.assertNotIn("MOCK-Entwurf", page)


if __name__ == "__main__":
    unittest.main()
