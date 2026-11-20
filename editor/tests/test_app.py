"""Drives the real Streamlit screen (editor/app.py) offline with Streamlit's AppTest. No browser, no network, no real data."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from streamlit.testing.v1 import AppTest
except ImportError:                                   # pragma: no cover
    AppTest = None

from editor import llm
from editor.tests.fixtures import a_style_batch, mutated, sample_batch, team_draft_batch, write_batch

APP = str(Path(__file__).resolve().parents[1] / "app.py")
TRENDS = Path(__file__).resolve().parents[2] / "data" / "trends"
FALLBACK = "Offline candidate ranking (fallback, not Person A's pitches)"


def btn(at, prefix):
    return next((b for b in at.button if b.label.startswith(prefix)), None)


def texts(at):
    return [x.value for x in (list(at.markdown) + list(at.caption) + list(at.warning) + list(at.error) + list(at.info) + list(at.success))]


def outside_expanders(at):
    """Texts on the page that are NOT inside an expander: what the editor sees without opening anything."""
    from collections import Counter
    inside = Counter()
    for e in at.expander:
        inside.update([m.value for m in e.markdown] + [c.value for c in e.caption] + [w.value for w in e.warning])
    out = []
    for text in texts(at):
        if inside.get(text, 0) > 0:
            inside[text] -= 1
        else:
            out.append(text)
    return out


def inside_expanders(at, label_prefix):
    return [m.value for e in at.expander if e.label.startswith(label_prefix) for m in e.markdown]


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ScreenTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def screen(self, path):
        """Run the app with EDITOR_PROPOSALS_JSON=path and no other configuration (no archive, no LLM, no real data)."""
        fake = lambda name: str(path) if name == "EDITOR_PROPOSALS_JSON" else ""          # noqa: E731
        for p in (mock.patch.object(llm, "_env", fake), mock.patch("editor.archive._env", fake)):
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(APP, default_timeout=60).run()
        self.assertFalse(at.exception, at.exception)
        return at

    # ---- a representative local Person A batch
    def test_five_pitches_in_a_order_with_source_label_and_no_rerun(self):
        at = self.screen(write_batch(self.dir))
        self.assertTrue(any("Person A saved batch · file batch.json" in t for t in texts(at)))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        heads = [m.value for m in at.markdown if m.value.startswith("### #")]
        self.assertEqual([h.split(" ")[1] for h in heads], ["#1", "#2", "#3", "#4", "#5"])
        self.assertIn("Pastinake", heads[0])
        self.assertEqual(len([b for b in at.button if b.label == "Choose this pitch"]), 5)
        self.assertTrue(btn(at, "Generate two recipes").disabled)                           # nothing chosen yet
        self.assertIsNone(btn(at, "None of these fit"))                                    # fixed batch: no rerun
        self.assertTrue(any("a fixed batch, so" in t for t in texts(at)))
        self.assertTrue(any("not recalculated here" in t for t in texts(at)))
        # the choices come first: title, one angle, one short why-now, a Choose button; nothing else is visible
        visible = outside_expanders(at)
        for label in ("**Recipe angle:**", "**Why now:**"):
            self.assertEqual(sum(t.startswith(label) for t in visible), 5, label)
        self.assertFalse(any(t.startswith(("**Brand fit:**", "**Prior coverage", "Prior coverage:", "Original", "Trend score")) for t in visible))
        self.assertEqual(sum(t.startswith("**Brand fit:**") for t in texts(at)), 5)         # brand reasoning moved under View evidence
        self.assertEqual(len([e for e in at.expander if e.label == "View evidence"]), 5)
        self.assertEqual(len(at.warning), 0)                                                # one compact notice, no stack of boxes
        self.assertEqual(len(at.info), 1)
    def test_prior_coverage_is_honest_on_screen(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        every = "\n".join(texts(at))
        self.assertIn("archive not available", every)                                       # Grünkohl: unavailable ...
        self.assertIn("no credible comparable recipe", every)                               # ... differs from Quitte: no match
        self.assertIn("2 comparable recipe(s)", every)
        self.assertIn("not assessed", every)
        details = "\n".join(inside_expanders(at, "Batch details"))
        self.assertIn("Prior coverage could not be checked for 1 of 5 pitches", details)    # the compact notice carries the honest gap
        self.assertIn("1 note", "\n".join(i.value for i in at.info))
        with_date = [t for t in texts(at) if "2020-08" in t.replace("\\", "")]
        self.assertTrue(with_date)                                                          # traceability: raw dates are still reachable ...
        for t in with_date:                                                                 # ... but only in the labelled evidence line
            self.assertIn("NOT publication dates", t)
        coverage_blocks = [m.value for m in at.markdown if m.value.startswith("**Prior coverage")]
        self.assertEqual(len(coverage_blocks), 5)                                           # the full text of every pitch sits in "View evidence"
        self.assertFalse(any("2020" in b.replace("\\", "") for b in coverage_blocks))
        self.assertFalse(any(t.startswith(("**Prior coverage", "Prior coverage")) for t in outside_expanders(at)))
    def test_choose_generate_review_approve_exports_two_cards(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-quitte").click().run()
        self.assertTrue(any(s.value == "Selected" for s in at.success))
        at.text_area[0].set_value("weeknight-friendly").run()
        self.assertFalse(btn(at, "Generate two recipes").disabled)
        btn(at, "Generate two recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        wf = at.session_state["wf"]
        self.assertEqual((wf.stage, wf.selected["id"], wf.selected["rank"]), ("review", "proposal-quitte", 3))
        approve = btn(at, "Approve both recipes")
        self.assertFalse(approve.disabled)
        with mock.patch("editor.workflow.DEFAULT_CARDS", self.dir / "cards"):
            wf.cards_dir = self.dir / "cards"
            approve.click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["wf"].stage, "approved")
        self.assertEqual(len(list((self.dir / "cards").glob("*.html"))), 2)

    def test_hard_block_still_applies_on_screen(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-pastinake").click().run()
        at.text_area[0].set_value("demo-stuck").run()
        btn(at, "Generate two recipes").click().run()
        self.assertTrue(btn(at, "Approve both recipes").disabled)
        self.assertTrue(at.error[0].value.startswith("**Blocked.**"))
        self.assertIsNone(btn(at, "Acknowledge"))                                          # hard issues offer no dismissal
        self.assertIsNotNone(btn(at, "Discard these recipes"))

    # ---- review: easier comparison, mock labelling, concrete before/after
    def test_compact_card_keeps_the_long_texts_in_view_evidence(self):
        long_why = "Erster Satz zum Trend. " + "Sehr ausführliche Begründung mit vielen Details. " * 12
        long_brand = "Passt zur Marke, weil saisonal. " + "Weitere lange Ausführungen zur Marke. " * 12
        def f(d):
            d["proposals"][0]["trend"]["why_relevant"] = long_why
            d["proposals"][0]["brand_fit"]["reasoning"] = long_brand
        at = self.screen(write_batch(self.dir, mutated(f)))
        btn(at, "Load the five pitches").click().run()
        visible_why = next(t for t in outside_expanders(at) if t.startswith("**Why now:**"))
        self.assertLessEqual(len(visible_why), 180)                                          # one short sentence, not a paragraph
        self.assertIn("Erster Satz zum Trend", visible_why)
        self.assertFalse(any(t.startswith("**Brand fit:**") for t in outside_expanders(at)))   # brand reasoning is not on the card
        full = "\n".join(t.replace("\\", "") for t in texts(at) if t.startswith(("**Why now (full):**", "**Brand fit:**")))
        self.assertIn("Weitere lange Ausführungen zur Marke", full)                          # nothing is lost, it lives in the expander
        self.assertIn("Sehr ausführliche Begründung", full)
        self.assertEqual([e.label for e in at.expander if e.label == "View evidence"], ["View evidence"] * 5)
    def test_missing_publication_date_is_not_shown_as_a_value(self):
        def f(d):
            for r in d["proposals"][0]["archive"]["similar_recipes"]:
                r.pop("published"); r.pop("date_source")
                r["publication_date"] = None
        at = self.screen(write_batch(self.dir, mutated(f)))
        btn(at, "Load the five pitches").click().run()
        every = "\n".join(texts(at))
        self.assertNotIn("publication_date=None", every)
        self.assertNotIn("None", every.replace("None%", ""))

    def test_mock_drafts_are_labelled_and_the_concrete_correction_is_shown_before_approval(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-pastinake").click().run()
        btn(at, "Generate two recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        every = "\n".join(texts(at))
        self.assertIn("Mock drafts: fixed sample recipes (lentil soup)", every)             # mock label stays visible
        self.assertIn("NOT generated from the selected pitch", every)
        labels = [e.label for e in at.expander]
        self.assertTrue(any(l.endswith("· Mock draft") for l in labels), labels)
        self.assertFalse(any("AI-generated draft" in l for l in labels), labels)
        # the status leads the screen
        order = [(e.type, str(getattr(e, "value", ""))) for e in at.main.children.values()]
        first_status = next(i for i, (t, v) in enumerate(order) if t in ("success", "error") and ("Ready to approve" in v or "Blocked" in v))
        pos_selected = next(i for i, (t, v) in enumerate(order) if t == "info" and "Selected" in v)
        self.assertLess(first_status, pos_selected)
        self.assertTrue(at.success[0].value.startswith("**Ready to approve.**"))
        # exactly ONE before/after correction beside the decision controls; the full history is collapsed
        visible = outside_expanders(at)
        self.assertEqual(sum(t.startswith("Before:") for t in visible), 1)
        self.assertEqual(sum(t.startswith("After:") for t in visible), 1)
        plain = every.replace("\\", "")
        self.assertIn("Rote Linsensuppe mit Zitrone · Step 3", plain)
        self.assertIn("Before: Die Suppe aufkochen", plain)
        self.assertIn("2 EL Zitronensaft, Salz und Pfeffer abschmecken", plain)
        corr = [c for c in at.columns if any("Latest correction" in m.value for m in c.markdown)]
        self.assertEqual(len(corr), 1)
        self.assertTrue(any(b.label.startswith("Approve") for c in at.columns for b in c.button))      # the controls live in the sibling column
        pos_decision = next(i for i, (t, v) in enumerate(order) if t == "subheader" and "Your decision" in v)
        self.assertGreater(pos_decision, first_status)
        history = [e for e in at.expander if e.label.startswith("Review history")]
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0].proto.expanded)
        self.assertIn("(2 rounds)", history[0].label)
        self.assertEqual([e for e in at.expander if e.label.startswith("Round ")], [])             # no per-round expanders on the page
        wf = at.session_state["wf"]
        with mock.patch("editor.workflow.DEFAULT_CARDS", self.dir / "cards"):
            wf.cards_dir = self.dir / "cards"
            btn(at, "Approve both recipes").click().run()
        self.assertTrue(any("(mock drafts)" in s.value for s in at.success))
        for card in (self.dir / "cards").glob("*.html"):
            page = card.read_text(encoding="utf-8")
            self.assertIn("MOCK-Entwurf", page)
            self.assertNotIn("KI-generierter Rezeptentwurf", page)
    def test_blocked_leads_the_review_screen_and_approve_is_disabled(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-pastinake").click().run()
        at.text_area[0].set_value("demo-stuck").run()
        btn(at, "Generate two recipes").click().run()
        self.assertTrue(at.error[0].value.startswith("**Blocked.**"))
        self.assertIn("2 hard issue(s) open", at.error[0].value)
        self.assertEqual(len(at.success), 0)                                                # no "ready" banner while blocked
        self.assertTrue(btn(at, "Approve both recipes").disabled)
        self.assertTrue(any("open hard issues above remain" in c.value for c in at.caption))
        self.assertTrue(any("Mock drafts" in w.value for w in at.warning))                  # mock label still visible

    def test_ready_banner_names_soft_warnings_that_do_not_block(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-pastinake").click().run()
        at.text_area[0].set_value("demo-soft").run()
        btn(at, "Generate two recipes").click().run()
        self.assertIn("Ready to approve", at.success[0].value)
        self.assertIn("1 soft warning(s) stay visible and do not block", at.success[0].value)
        self.assertFalse(btn(at, "Approve both recipes").disabled)

    def test_notice_details_are_collapsed_until_asked_for(self):
        at = self.screen(write_batch(self.dir, a_style_batch()))
        btn(at, "Load the five pitches").click().run()
        details = [e for e in at.expander if e.label.startswith("Batch details")]
        self.assertEqual(len(details), 1)
        self.assertFalse(details[0].proto.expanded)
        self.assertIn("2 notes", details[0].label)

    # ---- the first real batch from Person A (shape reproduced synthetically)
    def test_a_style_batch_loads_with_one_grouped_warning_and_flags_each_card(self):
        at = self.screen(write_batch(self.dir, a_style_batch()))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(len(at.warning), 0)                                                # one compact notice, nothing stacked
        notice = [i.value for i in at.info]
        self.assertEqual(len(notice), 1)
        self.assertIn("Person A saved batch", notice[0])
        self.assertIn("2 notes", notice[0])                                                 # templates + unchecked archive
        details = "\n".join(inside_expanders(at, "Batch details"))
        grouped = [l for l in details.splitlines() if "look like templates" in l]
        self.assertEqual(len(grouped), 1)                                                   # grouped, not one line per proposal
        self.assertIn("5 of 5 recipe angles", grouped[0])
        self.assertIn("could not be checked for 5 of 5 pitches", details)
        self.assertEqual(sum("⚠️ _placeholder_" in m.value for m in at.markdown), 5)       # every angle carries the marker
        self.assertEqual(len([b for b in at.button if b.label == "Choose this pitch"]), 5)
        self.assertFalse(any("no credible comparable recipe" in t for t in texts(at)))      # unavailable is never shown as "no match"
        self.assertEqual(sum(m.value.startswith("**Prior coverage: archive not available") for m in at.markdown), 5)   # stated for every pitch in its evidence
        heads = [m.value for m in at.markdown if m.value.startswith("### #")]
        self.assertIn("Cookie \\(Food\\)", heads[0])                                        # original labels preserved as supplied
    def test_a_style_batch_can_still_go_through_review_and_export(self):
        at = self.screen(write_batch(self.dir, a_style_batch()))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-cookie-food").click().run()
        btn(at, "Generate two recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["wf"].stage, "review")
        self.assertFalse(btn(at, "Approve both recipes").disabled)

    # ---- team draft for review
    def test_team_draft_is_visibly_labelled_not_approved_and_lists_its_changes(self):
        at = self.screen(write_batch(self.dir, team_draft_batch()))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        banner = " ".join(w.value for w in at.warning)
        self.assertIn("Team draft for Deyan's review", banner.replace("\\", ""))
        self.assertIn("Not approved by Person A", banner.replace("\\", ""))
        every = "\n".join(t.replace("\\", "") for t in texts(at))
        self.assertNotIn("Person A saved batch", every.replace("not Person A's approved batch", ""))   # must not look like A's own approved batch
        self.assertIn("This is a team draft, not Person A's approved batch.", "\n".join(inside_expanders(at, "Batch details")))
        self.assertEqual(len(at.warning), 1)                                                 # one compact notice
        self.assertEqual(len([b for b in at.button if b.label == "Choose this pitch"]), 5)
        self.assertEqual(sum(t.startswith("Team draft: what changed") or "what changed against Person A" in t for t in texts(at)), 5)
        self.assertIn("Title and angle rewritten.", every)
        self.assertIn("Original Recipe angle: Einfache X-Variante", every)
        self.assertIn("Ranking method as supplied: SYNTHETIC: 50% trend", every)
        self.assertIn("Original German source terms: 'pastinake rezept' (query, rising, +850%, index 0/100)", every)

    def test_team_draft_still_goes_through_review_and_export(self):
        at = self.screen(write_batch(self.dir, team_draft_batch()))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-linsen").click().run()
        btn(at, "Generate two recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["wf"].stage, "review")
        self.assertFalse(btn(at, "Approve both recipes").disabled)

    # ---- found by looking at the real screen in a browser
    def drafts_screen(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        next(b for b in at.button if b.key == "pick-proposal-pastinake").click().run()
        btn(at, "Generate two recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        return at

    def test_ingredient_amounts_read_like_the_card_not_like_a_float_table(self):
        at = self.drafts_screen()
        every = "\n".join(t.replace("\\", "") for t in texts(at))
        for line in ("- 250 g rote Linsen", "- 2 EL Olivenöl", "- 1 l Gemüsebrühe", "- 2 EL Zitronensaft", "- Salz", "- 1 Bund Petersilie"):
            self.assertIn(line, every)
        self.assertNotIn("0000", every)                                                     # the old table printed 250.0000 g
        self.assertEqual(len(at.dataframe) + len(at.table), 0)

    def test_the_drafts_being_approved_are_open_during_review(self):
        at = self.drafts_screen()
        drafts = [e for e in at.expander if e.label.endswith("· Mock draft")]
        self.assertEqual(len(drafts), 2)
        self.assertTrue(all(e.proto.expanded for e in drafts))

    def test_changed_words_are_highlighted_in_the_before_after_block(self):
        at = self.drafts_screen()
        block = "\n".join(m.value for m in at.markdown if m.value.startswith(("Before:", "After:")))
        self.assertIn(":red[~~", block)
        self.assertIn(":green[**", block)
        self.assertIn("Zitronensaft", next(m.value for m in at.markdown if m.value.startswith("After:")))

    def test_decision_trail_is_readable(self):
        at = self.drafts_screen()
        trail = [c.value for c in at.sidebar.caption]
        self.assertIn("Proposals loaded (5)", trail)
        self.assertIn("You chose: Pastinake", trail)
        self.assertIn("Two drafts created", trail)
        self.assertFalse(any("{" in t or "'n'" in t for t in trail), trail)

    def test_approval_shows_a_preview_and_a_download_for_each_card(self):
        at = self.drafts_screen()
        wf = at.session_state["wf"]
        with mock.patch("editor.workflow.DEFAULT_CARDS", self.dir / "cards"):
            wf.cards_dir = self.dir / "cards"
            btn(at, "Approve both recipes").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([t.label for t in at.tabs], ["Card 1: Rote Linsensuppe mit Zitrone", "Card 2: Linsen-Eintopf mit Kartoffeln"])
        self.assertEqual(len(at.get("download_button")), 2)
        self.assertEqual(len(at.get("iframe")), 2)                                          # the real A4 card, embedded
        self.assertFalse(any(c.language == "text" and str(self.dir) in c.value for c in at.code))   # no bare file-path boxes any more

    def test_theme_and_toolbar_config_ships_with_the_app(self):
        cfg = (Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('primaryColor = "#006642"', cfg)
        self.assertIn('toolbarMode = "minimal"', cfg)

    def test_evidence_does_not_repeat_texts_that_were_not_shortened(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(any(t.startswith(("**Why now (full):**", "**Brand fit (full):**")) for t in texts(at)))   # all synthetic texts are short

    # ---- review findings: incomplete optional data must not crash the pitch screen
    def test_wikimedia_with_views_but_no_percentage_renders(self):
        def f(d):
            d["proposals"][0]["trend"]["wikimedia"] = {"status": "available", "article": "Pastinake", "score": None, "points": [],
                                                       "error": None, "views_latest_7d": 120}
        at = self.screen(write_batch(self.dir, mutated(f)))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        every = "\n".join(texts(at))
        self.assertIn("latest 7-day views 120", every)
        self.assertNotIn("None%", every)
        self.assertEqual(len([b for b in at.button if b.label == "Choose this pitch"]), 5)

    def test_odd_optional_fields_render_without_crashing(self):
        def f(d):
            p = d["proposals"]
            p[0]["trend"]["wikimedia"] = {"status": "available", "article": ["x"], "score": "high", "views_previous_7d": "many",
                                          "views_latest_7d": 120, "change_pct": None}
            p[1]["trend"]["components"] = [1, 2, 3]
            p[1]["trend"]["sparkline"] = "x"
            p[2]["brand_fit"].update(fit=["a"], score=None)
            p[2]["rank_score"] = float("nan")
            p[3]["archive"]["match_count"] = "many"
            p[4]["archive"]["similar_recipes"][0].update(category=["x"], why={"a": 1})
            p[4]["trend"]["wikimedia"] = {"status": "unavailable"}
        at = self.screen(write_batch(self.dir, mutated(f)))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(len([b for b in at.button if b.label == "Choose this pitch"]), 5)

    def test_supplied_text_cannot_inject_markdown_links_or_images(self):
        evil = "![x](http://evil.example/p.png) [click](http://evil.example)"
        def f(d):
            p = d["proposals"][0]
            p["title"] = "T " + evil
            p["topic"] = "Pastinake " + evil
            p["recipe_ideas"] = ["Angle " + evil, "Alt " + evil]
            p["trend"]["why_relevant"] = "Why " + evil
            p["trend"]["sources"] = ["Src " + evil]
            p["brand_fit"]["reasoning"] = "Brand " + evil
            p["archive"]["similar_recipes"][0].update(title="A " + evil, category="C " + evil, why="W " + evil)
            p["archive"]["assumption"] = "As " + evil
            d["rejected_topics"][0].update(topic="R " + evil, reason="Why " + evil)
        at = self.screen(write_batch(self.dir, mutated(f)))
        btn(at, "Load the five pitches").click().run()
        self.assertFalse(at.exception, at.exception)
        leaked = [t for t in texts(at) if "](http" in t or "![" in t]
        self.assertEqual(leaked, [])
        self.assertTrue(any("evil.example" in t.replace("\\", "") for t in texts(at)))     # the text is shown, just not as markup

    # ---- missing / malformed batches fail visibly, never silently replaced
    def test_missing_batch_fails_visibly_without_mock_fallback(self):
        at = self.screen(self.dir / "does-not-exist.json")
        errors = " ".join(e.value for e in at.error)
        self.assertIn("cannot be used", errors)
        self.assertIn("not found", errors)
        self.assertIn("Nothing was replaced by mock data", errors)
        self.assertTrue(btn(at, "Load the five pitches").disabled)
        self.assertEqual(at.session_state["wf"].proposals, [])
        self.assertEqual(at.session_state["wf"].stage, "idle")

    def test_malformed_batch_lists_every_problem(self):
        def f(d):
            d["proposals"][1]["id"] = d["proposals"][0]["id"]
            d["proposals"][2]["rank"] = 1
            d["proposals"][3]["recipe_ideas"] = []
        at = self.screen(write_batch(self.dir, mutated(f)))
        errors = " ".join(e.value for e in at.error)
        for expect in ("duplicate proposal id", "duplicate rank 1", "recipe_ideas"):
            self.assertIn(expect, errors)
        self.assertTrue(btn(at, "Load the five pitches").disabled)

    def test_invalid_json_is_a_readable_error(self):
        path = self.dir / "broken.json"
        path.write_text("{oops")
        at = self.screen(path)
        self.assertIn("not valid JSON", " ".join(e.value for e in at.error))

    # ---- the opt-in fallback is separately labelled and invents nothing
    @unittest.skipUnless((TRENDS / "google-trends").is_dir(), "provided trend data not present")
    def test_fallback_is_opt_in_labelled_and_invents_nothing(self):
        at = self.screen(self.dir / "does-not-exist.json")
        self.assertEqual(at.session_state["wf"].proposals, [])                              # no silent fallback
        at.sidebar.radio[0].set_value(FALLBACK).run()
        self.assertFalse(at.exception, at.exception)
        btn(at, "Run the offline candidate ranking").click().run()
        self.assertFalse(at.exception, at.exception)
        every = "\n".join(texts(at))
        self.assertTrue(any("Offline candidate ranking" in w.value and "not Person A's pitches" in w.value for w in at.warning))
        self.assertEqual(len([b for b in at.button if b.label == "Choose this topic"]), 5)     # topics, not pitches: no angle exists yet
        self.assertEqual([b for b in at.button if b.label == "Choose this pitch"], [])
        self.assertIn("No recipe angle yet", every)
        self.assertIn("not assessed", every)
        self.assertFalse(any(t.startswith("**Recipe angle:**") for t in texts(at)))
        self.assertIsNotNone(btn(at, "None of these fit"))                                  # a real rerun exists here
        for p in at.session_state["wf"].proposals:
            self.assertIsNone(p["brand_fit"]["score"])
            self.assertEqual(p["recipe_ideas"], [])
    def test_switching_the_source_starts_a_clean_workflow(self):
        at = self.screen(write_batch(self.dir))
        btn(at, "Load the five pitches").click().run()
        self.assertEqual(at.session_state["wf"].stage, "proposals")
        at.sidebar.radio[0].set_value(FALLBACK).run()
        self.assertEqual(at.session_state["wf"].stage, "idle")


if __name__ == "__main__":
    unittest.main()
