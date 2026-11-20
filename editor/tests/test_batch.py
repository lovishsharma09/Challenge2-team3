import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from editor import batch as B
from editor.agents import Agents
from editor.contract import check_proposals
from editor.display import coverage_summary, evidence_details, md, pitch_fields, trend_summary, wikimedia_summary
from editor.tests.fixtures import mutated, sample_batch, team_draft_batch, write_batch
from editor.workflow import EditorWorkflow, WorkflowError

SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "proposals.schema.json"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def load(self, data=None, name="batch.json"):
        return B.load_batch(write_batch(self.dir, data, name))

    def errors(self, fn):
        with self.assertRaises(B.BatchError) as ctx:
            self.load(mutated(fn))
        return " | ".join(ctx.exception.messages)


class LoadTest(Base):
    def test_valid_batch_keeps_a_order_originals_and_labels_the_source(self):
        b = self.load()
        self.assertEqual([p["rank"] for p in b.proposals], [1, 2, 3, 4, 5])
        self.assertEqual(b.proposals, sample_batch()["proposals"])              # nothing recalculated or rewritten
        self.assertIn("batch.json", b.source_label)
        self.assertIn(b.sha256[:12], b.source_label)
        self.assertIn("Person A saved batch", b.source_label)
        self.assertEqual(b.rejected[0]["topic"], "Dubai-Schokolade")
        self.assertEqual(b.warnings, [])
        check_proposals((b.proposals, b.rejected))                              # fits the existing contract

    def test_fixture_is_valid_against_the_published_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.validate(sample_batch(), json.loads(SCHEMA.read_text(encoding="utf-8")))

    def test_ranks_define_the_order_and_a_file_order_mismatch_is_flagged(self):
        data = sample_batch()
        data["proposals"].reverse()
        b = self.load(data)
        self.assertEqual([p["rank"] for p in b.proposals], [1, 2, 3, 4, 5])
        self.assertTrue(any("differs from the ranks" in w for w in b.warnings))

    def test_non_contiguous_ranks_warn_but_load(self):
        def f(d):
            for i, p in enumerate(d["proposals"]):
                p["rank"] = [2, 3, 5, 7, 11][i]
        b = self.load(mutated(f))
        self.assertTrue(any("instead of 1-5" in w for w in b.warnings))

    def test_template_angles_are_flagged(self):
        def f(d):
            d["proposals"][0]["recipe_ideas"] = ["Einfache Pastinake-Variante in einem 30-Minuten-Format"]
        warnings = self.load(mutated(f)).warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 of 5 recipe angles look like templates", warnings[0])
        self.assertIn("proposals #1", warnings[0])

    def test_many_template_angles_give_one_grouped_warning(self):
        def f(d):
            for p in d["proposals"]:
                p["recipe_ideas"] = [f"Einfache {p['topic']}-Variante in einem 30-Minuten-Format", f"Saisonale {p['topic']}-Version zum Vorbereiten"]
        warnings = self.load(mutated(f)).warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn("5 of 5 recipe angles look like templates", warnings[0])
        self.assertIn("#1, #2, #3, #4, #5", warnings[0])
        self.assertTrue(B.is_template_angle("Klassische Kürbis-Version mit klarer Wochenendoption"))
        self.assertFalse(B.is_template_angle("Kürbis-Ravioli mit Salbeibutter"))
        self.assertFalse(B.is_template_angle(None))

    def test_loading_does_not_mutate_the_file_or_share_objects(self):
        path = write_batch(self.dir)
        before = path.read_bytes()
        b = B.load_batch(path)
        b.proposals[0]["title"] = "changed"
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(B.load_batch(path).proposals[0]["title"], "changed")


class InvalidBatchTest(Base):
    def test_missing_and_unreadable_files(self):
        for arg, expect in ((None, "no batch file"), ("", "no batch file"), (self.dir / "nope.json", "not found")):
            with self.assertRaises(B.BatchError) as ctx:
                B.load_batch(arg)
            self.assertIn(expect, str(ctx.exception))
        for content, expect in ((b"{not json", "not valid JSON"), (b"\xff\xfe\x00", "UTF-8"), (b"[" * 200000, "not valid JSON"),
                                (b"[]", "JSON object"), (b'"x"', "JSON object"), (b"{}", "'proposals' must be a list"),
                                (b'{"proposals": {}}', "'proposals' must be a list")):
            path = self.dir / "bad.json"
            path.write_bytes(content)
            with self.assertRaises(B.BatchError) as ctx:
                B.load_batch(path)
            self.assertIn(expect, str(ctx.exception))

    def test_oversized_file_is_refused_before_parsing(self):
        path = self.dir / "big.json"
        path.write_bytes(b" " * (B.MAX_BYTES + 1))
        with self.assertRaises(B.BatchError) as ctx:
            B.load_batch(path)
        self.assertIn("too large", str(ctx.exception))

    def test_wrong_number_of_proposals(self):
        self.assertIn("exactly 5 proposals, found 4", self.errors(lambda d: d["proposals"].pop()))
        self.assertIn("found 6", self.errors(lambda d: d["proposals"].append(copy.deepcopy(d["proposals"][0]) | {"id": "x", "rank": 6})))
        self.assertIn("found 0", self.errors(lambda d: d.update(proposals=[])))

    def test_duplicate_ids_and_ranks_are_visible_failures(self):
        self.assertIn("duplicate proposal id", self.errors(lambda d: d["proposals"][1].update(id=d["proposals"][0]["id"])))
        msg = self.errors(lambda d: d["proposals"][1].update(rank=1))
        self.assertIn("duplicate rank 1", msg)
        self.assertIn("ambiguous", msg)

    def test_bad_ranks_and_scores(self):
        for bad in (0, -1, 1.5, "2", None, True):
            self.assertIn("'rank' must be an integer >= 1", self.errors(lambda d, b=bad: d["proposals"][0].update(rank=b)))
        self.assertIn("rank_score", self.errors(lambda d: d["proposals"][0].update(rank_score="high")))

    def test_missing_required_fields_are_named(self):
        for key in B.REQUIRED:
            self.assertIn(f"missing field '{key}'", self.errors(lambda d, k=key: d["proposals"][2].pop(k)))

    def test_recipe_angle_and_brand_reasoning_are_required(self):
        for bad in ([], [""], ["  "], [None], "text"):
            self.assertIn("concrete recipe angle", self.errors(lambda d, b=bad: d["proposals"][0].update(recipe_ideas=b)))
        self.assertIn("brand_fit.reasoning", self.errors(lambda d: d["proposals"][0]["brand_fit"].update(reasoning="")))
        self.assertIn("brand_fit.reasoning", self.errors(lambda d: d["proposals"][0]["brand_fit"].pop("reasoning")))
        self.assertIn("'brand_fit' must be an object", self.errors(lambda d: d["proposals"][0].update(brand_fit="fits")))

    def test_trend_evidence_must_be_traceable(self):
        self.assertIn("trend.sources", self.errors(lambda d: d["proposals"][0]["trend"].update(sources=[])))
        self.assertIn("trend.why_relevant", self.errors(lambda d: d["proposals"][0]["trend"].update(why_relevant=" ")))
        self.assertIn("trend.points", self.errors(lambda d: d["proposals"][0]["trend"].update(points=[{"date": "x"}])))
        self.assertIn("trend.wikimedia.status", self.errors(lambda d: d["proposals"][0]["trend"]["wikimedia"].update(status="maybe")))

    def test_archive_block_must_be_consistent(self):
        self.assertIn("matches_found but lists no recipe", self.errors(lambda d: d["proposals"][0]["archive"].update(similar_recipes=[])))
        self.assertIn("no_match_found but is inconsistent", self.errors(
            lambda d: d["proposals"][2]["archive"].update(similar_recipes=[{"title": "X"}])))
        self.assertIn("archive_unavailable but is inconsistent", self.errors(lambda d: d["proposals"][3]["archive"].update(available=True)))
        self.assertIn("archive.match_status must be one of", self.errors(lambda d: d["proposals"][0]["archive"].update(match_status="lots")))
        self.assertIn("archive.repetition_risk", self.errors(lambda d: d["proposals"][0]["archive"].update(repetition_risk="severe")))
        self.assertIn("archive.assumption is missing", self.errors(lambda d: d["proposals"][0]["archive"].pop("assumption")))
        self.assertIn("with a title", self.errors(lambda d: d["proposals"][0]["archive"].update(similar_recipes=[{"category": "x"}])))

    def test_rejected_topics_shape_and_limits(self):
        self.assertIn("rejected_topics", self.errors(lambda d: d.update(rejected_topics="none")))
        self.assertIn("rejected_topics #1", self.errors(lambda d: d["rejected_topics"].__setitem__(0, {"topic": "x"})))
        self.assertIn("too long", self.errors(lambda d: d["proposals"][0].update(title="x" * (B.MAX_TEXT + 1))))
        self.assertIn("similar_recipes", self.errors(lambda d: d["proposals"][0]["archive"].update(
            similar_recipes=[{"title": f"t{i}"} for i in range(B.MAX_SIMILAR + 1)])))

    def test_all_problems_are_reported_at_once(self):
        def f(d):
            d["proposals"].pop()
            d["proposals"][0].update(rank=2)
            d["proposals"][1]["recipe_ideas"] = []
        with self.assertRaises(B.BatchError) as ctx:
            self.load(mutated(f))
        self.assertGreaterEqual(len(ctx.exception.messages), 3)


JUNK = [None, True, False, 0, -1, 1.5, "", " ", "x", [], {}, [None], [[]], {"a": 1}, float("nan"), float("inf"), 10 ** 40]


def paths(node, prefix=(), depth=0):
    """Every dict key / list index in the sample batch (containers and leaves), up to depth 5."""
    if depth > 5:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield prefix + (k,)
            yield from paths(v, prefix + (k,), depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield prefix + (i,)
            yield from paths(v, prefix + (i,), depth + 1)


def put(data, path, value, delete=False):
    node = data
    for key in path[:-1]:
        node = node[key]
    if delete:
        node.pop(path[-1]) if isinstance(node, dict) else node.__setitem__(path[-1], None)
    else:
        node[path[-1]] = value


class TeamDraftTest(Base):
    def test_a_team_draft_is_labelled_as_such_never_as_person_a(self):
        b = self.load(team_draft_batch())
        self.assertEqual(b.draft_label, "Team draft for Deyan's review")
        self.assertEqual(b.draft_status, "Not approved by Person A")
        self.assertIn("proposals.json (sha256 ab12cd34ef56)", b.based_on)
        self.assertTrue(b.source_label.startswith("Team draft for Deyan's review · Not approved by Person A"))
        self.assertNotIn("Person A saved batch", b.source_label)
        self.assertIn("batch.json", b.source_label)

    def test_an_ordinary_batch_keeps_the_person_a_label(self):
        b = self.load()
        self.assertEqual(b.draft_label, "")
        self.assertTrue(b.source_label.startswith("Person A saved batch"))

    def test_odd_source_blocks_never_crash_or_fake_a_draft(self):
        for source in (None, [], "x", 5, {}, {"kind": "other"}, {"kind": ["team_draft"]}):
            data = sample_batch()
            data["source"] = source
            self.assertEqual(self.load(data).draft_label, "", source)
        data = sample_batch()
        data["source"] = {"kind": "team_draft", "label": ["x"], "status": 5, "based_on": "x"}      # draft with broken fields: safe defaults
        b = self.load(data)
        self.assertEqual((b.draft_label, b.draft_status, b.based_on), ("Team draft for review", "Not approved", ""))
        data["source"] = {"kind": "team_draft", "label": "L" * 1000, "status": "S", "based_on": {"file": "f", "sha256": 7}}
        b = self.load(data)
        self.assertLessEqual(len(b.draft_label), 200)

    def test_a_draft_cannot_be_validated_into_approved_wording(self):
        b = self.load(team_draft_batch())
        self.assertNotIn("approved by Person A", b.source_label.replace("Not approved by Person A", ""))


class RobustnessTest(Base):
    """Review finding: wrong JSON types must be readable validation errors, never crashes (loader or display)."""

    def test_unhashable_values_where_an_enum_is_expected_are_readable_errors(self):
        for fn, expect in ((lambda d: d["proposals"][0]["archive"].update(match_status=[]), "archive.match_status must be one of"),
                           (lambda d: d["proposals"][0]["archive"].update(match_status={}), "archive.match_status must be one of"),
                           (lambda d: d["proposals"][0]["archive"].update(repetition_risk=["low"]), "archive.repetition_risk must be one of"),
                           (lambda d: d["proposals"][0]["trend"]["wikimedia"].update(status={}), "trend.wikimedia.status must be one of")):
            self.assertIn(expect, self.errors(fn))

    def test_every_wrong_type_at_every_position_is_an_error_or_loads_never_a_crash(self):
        base, checked, loaded = sample_batch(), 0, 0
        for path in paths(base):
            for value in JUNK + ["<delete>"]:
                data = copy.deepcopy(base)
                put(data, path, None if value == "<delete>" else value, delete=value == "<delete>")
                try:
                    errors, warnings = B.validate_batch(data)           # must never raise
                except Exception as exc:                                 # noqa: BLE001
                    self.fail(f"validate_batch crashed at {path} with {value!r}: {type(exc).__name__}: {exc}")
                checked += 1
                loaded += not errors
        self.assertGreater(checked, 2000)
        self.assertGreater(loaded, 100)                                 # plenty of odd-but-accepted variants for the display fuzz

    def test_load_batch_only_ever_raises_batch_error(self):
        for path in list(paths(sample_batch()))[:60]:
            for value in JUNK:
                data = copy.deepcopy(sample_batch())
                put(data, path, value)
                try:
                    self.load(data)
                except B.BatchError:
                    pass

    def test_display_never_crashes_on_any_batch_the_loader_accepts(self):
        base, shown = sample_batch(), 0
        for path in paths(base):
            for value in JUNK + ["<delete>"]:
                data = copy.deepcopy(base)
                put(data, path, None if value == "<delete>" else value, delete=value == "<delete>")
                if B.validate_batch(data)[0]:
                    continue
                for p in data["proposals"]:
                    for fn in (coverage_summary, wikimedia_summary, pitch_fields, evidence_details, trend_summary):
                        try:
                            fn(p)
                        except Exception as exc:                         # noqa: BLE001
                            self.fail(f"{fn.__name__} crashed for {path}={value!r}: {type(exc).__name__}: {exc}")
                    shown += 1
        self.assertGreater(shown, 500)

    def test_wikimedia_line_shows_only_the_values_that_exist(self):
        def line(**w):
            return wikimedia_summary({"trend": {"wikimedia": {"status": "available", "article": "Pastinake", **w}}})
        self.assertEqual(line(views_latest_7d=120)[1], "Wikipedia pageviews (Pastinake): latest 7-day views 120.")      # the reported case
        self.assertEqual(line(views_previous_7d=80)[1], "Wikipedia pageviews (Pastinake): previous 7-day views 80.")
        self.assertIn("7-day views 80 → 120", line(views_previous_7d=80, views_latest_7d=120, change_pct=50.0)[1])
        self.assertIn("change +50%", line(views_previous_7d=80, views_latest_7d=120, change_pct=50.0)[1])
        self.assertEqual(line(change_pct=-12.4)[1], "Wikipedia pageviews (Pastinake): change -12%.")
        self.assertIn("without any numbers", line()[1])
        for junk in ("n/a", None, [], {}, True, float("nan"), float("inf")):
            text = line(views_latest_7d=junk, change_pct=junk, score=junk, views_previous_7d=junk)[1]
            self.assertIn("without any numbers", text)
            self.assertNotIn("None", text)
            self.assertNotIn("nan", text.casefold().replace("n/a", ""))
        self.assertEqual(line(views_latest_7d=120, change_pct=None)[0], "ok")

    def test_foreign_trend_components_are_ignored_not_crashed_on(self):
        for comps in ([], {}, "x", {"score": "high"}, {"score": 1, "google": 2}, {"score": 1, "google": 2, "rising_increase_pct": None}):
            self.assertIsNone(trend_summary({"trend": {"components": comps}}))

    def test_markdown_escape_neutralises_images_and_links(self):
        for text in ("![x](http://evil.example/p.png)", "[click](http://evil.example)", "**bold** _it_ `code` <b>x</b>"):
            out = md(text)
            self.assertNotIn("](", out)
            self.assertNotIn("![", out)
            self.assertNotIn("**", out.replace("\\*", ""))


class SelfCheckTest(Base):
    def test_summary_and_command_line_check(self):
        import subprocess, sys
        path = write_batch(self.dir)
        text = B.summarize(B.load_batch(path))
        self.assertIn("#1 proposal-pastinake", text)
        self.assertIn("rejected topics: 1", text)
        root = Path(__file__).resolve().parents[2]
        ok = subprocess.run([sys.executable, "-m", "editor.batch", str(path)], cwd=root, capture_output=True, text=True,
                            env={"PYTHONPATH": str(root)})
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("5 pitches in A's order", ok.stdout)
        bad = write_batch(self.dir, mutated(lambda d: d["proposals"].pop()), name="bad.json")
        res = subprocess.run([sys.executable, "-m", "editor.batch", str(bad)], cwd=root, capture_output=True, text=True,
                             env={"PYTHONPATH": str(root)})
        self.assertEqual(res.returncode, 1)
        self.assertIn("INVALID BATCH", res.stdout)
        self.assertIn("exactly 5 proposals", res.stdout)


class FixedBatchTest(Base):
    def test_propose_returns_the_supplied_pitches_unchanged_and_cannot_rerun(self):
        b = self.load()
        propose = B.propose_from_batch(b)
        self.assertIs(propose.supports_rerun, False)
        first, rejected = propose(set(), 5)
        self.assertEqual(first, sample_batch()["proposals"])                     # same order, same rank_score, nothing re-scored
        self.assertEqual(propose({"Pastinake"}, 5), ([], []))                    # no replacement exists
        first[0]["title"] = "mutated"
        self.assertNotEqual(propose(set(), 5)[0][0]["title"], "mutated")          # callers get copies

    def test_reject_all_is_disabled_and_never_silently_falls_back_to_mocks(self):
        with tempfile.TemporaryDirectory() as d:
            wf = EditorWorkflow(Agents(propose=B.propose_from_batch(self.load())), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            self.assertFalse(wf.can_reject_all())
            before = [p["id"] for p in wf.proposals]
            with self.assertRaises(WorkflowError) as ctx:
                wf.reject_all("none fit")
            self.assertIn("fixed batch", str(ctx.exception))
            self.assertEqual([p["id"] for p in wf.proposals], before)
            self.assertEqual(wf.stage, "proposals")
            self.assertNotIn("editor_rejected_all", Path(d, "a.jsonl").read_text(encoding="utf-8"))

    def test_review_flow_and_export_still_work_for_a_batch_pitch(self):
        with tempfile.TemporaryDirectory() as d:
            wf = EditorWorkflow(Agents(propose=B.propose_from_batch(self.load())), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            self.assertEqual([p["rank"] for p in wf.proposals], [1, 2, 3, 4, 5])
            wf.select("proposal-pastinake", "weeknight-friendly demo-soft")
            self.assertEqual(wf.stage, "review")
            self.assertEqual(wf.selected["id"], "proposal-pastinake")
            self.assertEqual(wf.selected["rank_score"], 85.5)                    # still exactly what A supplied
            self.assertTrue(wf.can_approve()[0])
            self.assertFalse(list(Path(d, "cards").glob("*")) if Path(d, "cards").exists() else [])   # nothing before approval
            wf.approve()
            self.assertEqual(len(wf.result["cards"]), 2)
            self.assertTrue(all(Path(c).is_file() for c in wf.result["cards"]))

    def test_hard_issues_still_block_for_a_batch_pitch(self):
        with tempfile.TemporaryDirectory() as d:
            wf = EditorWorkflow(Agents(propose=B.propose_from_batch(self.load())), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            wf.select("proposal-linsen", "demo-stuck")
            self.assertFalse(wf.can_approve()[0])
            with self.assertRaises(WorkflowError):
                wf.approve()


class CoverageDisplayTest(unittest.TestCase):
    def test_unavailable_is_distinct_from_no_match_and_from_matches(self):
        proposals = {p["topic"]: p for p in sample_batch()["proposals"]}
        unavailable = coverage_summary(proposals["Grünkohl"])
        no_match = coverage_summary(proposals["Quitte"])
        matches = coverage_summary(proposals["Pastinake"])
        self.assertEqual(unavailable[0], "warn")
        self.assertIn("archive not available", unavailable[1])
        self.assertIn("could NOT be checked", unavailable[1])
        self.assertIn("no credible comparable recipe", no_match[1])
        self.assertNotIn("not available", no_match[1])
        self.assertIn("2 comparable recipe(s)", matches[1])
        self.assertIn("SYNTHETIC Pastinakensuppe".replace(" ", " "), matches[1].replace("\\", ""))

    def test_dates_and_risk_labels_from_the_source_are_never_presented_as_facts(self):
        text = coverage_summary(sample_batch()["proposals"][0])[1]               # archive says repetition_risk "high", dates 2020-08-01
        self.assertNotIn("2020", text)
        self.assertNotIn("published", text.casefold().replace("publication dates are not shown", ""))
        self.assertNotIn("high", text.casefold())
        self.assertIn("not assessed", text)
        self.assertIn("not a repetition judgement", text)
        self.assertIn("CMS and import dates are not publication dates", text)

    def test_titles_are_markdown_escaped(self):
        p = sample_batch()["proposals"][0]
        p["archive"]["similar_recipes"] = [{"title": "**x** [click](http://evil.example)", "category": "<b>"}]
        text = coverage_summary(p)[1]
        self.assertNotIn("[click](http://evil.example)", text)

    def test_pitch_fields_keep_original_text_and_never_invent(self):
        f = pitch_fields(sample_batch()["proposals"][0])
        self.assertTrue(f["angle"].startswith("Ofen-Pastinaken"))
        self.assertEqual(len(f["more_angles"]), 1)
        empty = pitch_fields({"recipe_ideas": [], "brand_fit": {"score": None}, "trend": {}})
        self.assertEqual((empty["angle"], empty["why_now"], empty["brand_reason"]), (None, None, None))


if __name__ == "__main__":
    unittest.main()
