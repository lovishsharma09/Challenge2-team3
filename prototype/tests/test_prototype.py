"""Glue tests for the prototype (no network): Person A -> B handoff -> selection.json contract, C config, impact numbers,
demo cache round trip, and the page itself in demo mode via Streamlit's AppTest.
Run:  python -m unittest discover -s prototype/tests -t ."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prototype import adapters as ad      # noqa: E402
from prototype import ui                  # noqa: E402


def person_a_batch(n: int = 5) -> dict:
    """Five proposals in Person A's shape that pass Person B's strict batch validation."""
    props = []
    for i in range(1, n + 1):
        props.append({
            "id": f"proposal-topic-{i}", "title": f"Grünkohl-Gericht Nummer {i} mit Kartoffeln", "topic": f"Topic {i} (Food)", "rank": i,
            "rank_score": 80.0 - i, "rank_method": "test",
            "trend": {"score": 50 - i, "why_relevant": "Rising interest in the supplied Google Trends data.", "sources": ["Google Trends supplied data"],
                      "points": [{"date": "2026-11-18", "value": 50 - i, "source": "Google Trends Rising Topics", "increase_percent": "90 %"}],
                      "wikimedia": {"status": "available", "article": "Grünkohl", "score": 55, "error": None,
                                    "points": [{"date": f"2026-11-{d:02d}", "value": 100 + d, "source": "Wikimedia Pageviews", "article": "Grünkohl"} for d in range(1, 19)]}},
            "brand_fit": {"score": 78, "fit": "medium", "reasoning": "Alltagstauglich und saisonal.", "positive_signals": [], "negative_signals": []},
            "archive": {"status": "available", "available": True, "match_status": "matches_found" if i == 1 else "no_match_found",
                        "similar_recipes": [{"title": "Grünkohl klassisch", "published": "2024-01-10", "date_source": "DateCreated", "match_level": "whole"}] if i == 1 else [],
                        "repetition_risk": "medium" if i == 1 else "low", "content_gap": "Keine schnelle Pfanne im Archiv.", "assumption": "Matched against the export.",
                        "most_recent_comparable_publication": "2024-01-10" if i == 1 else None},
            "recipe_ideas": [f"Grünkohl-Pfanne {i} mit Bratkartoffeln und Speck", f"Grünkohl-Eintopf {i} mit Kassler"],
            "risks": [],
        })
    return {"proposals": props, "rejected_topics": [{"id": "proposal-x", "topic": "X (Food)", "reason": "Not in the top five.", "rank_score": 10.0}]}


class Handoff(unittest.TestCase):
    def test_editor_handoff_writes_selection_in_person_c_contract_and_audit(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            ad._write(run_dir / "proposals.json", person_a_batch())
            out = ad.editor_handoff(run_dir, "proposal-topic-2", "alltagstauglich, keine exotischen Zutaten\nweniger Sahne", selected_by="test")
            sel = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))
            for key in ("picks", "selected_ids", "steering_notes", "selected_by", "timestamp"):   # person_c/docs/CONTRACTS.md
                self.assertIn(key, sel)
            self.assertEqual(sel["picks"], 1)
            self.assertEqual(sel["selected_ids"], ["proposal-topic-2"])
            self.assertEqual(sel["steering_notes"], ["alltagstauglich, keine exotischen Zutaten", "weniger Sahne"])
            events = [e["event"] for e in out["trail"]]
            self.assertEqual(events, ["proposals_ready", "editor_selected"])          # Person B's audit log
            log = (run_dir / "editor_audit.jsonl").read_text(encoding="utf-8")
            self.assertIn('"editor_selected"', log)
            self.assertIn("proposal-topic-2", log)
            # Person C reads exactly this file
            run = ad.load_run(run_dir)
            self.assertEqual(run["selection"]["selected_ids"], ["proposal-topic-2"])
            self.assertEqual(run["handoff"]["trail"][-1]["event"], "editor_selected")

    def test_unknown_proposal_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            ad._write(run_dir / "proposals.json", person_a_batch())
            with self.assertRaises(Exception):
                ad.editor_handoff(run_dir, "nope", "")
            self.assertFalse((run_dir / "selection.json").exists())

    def test_person_c_accepts_the_handoff_offline(self):
        os.environ["OFFLINE"] = "1"
        try:
            with tempfile.TemporaryDirectory() as d:
                run_dir = Path(d)
                ad._write(run_dir / "proposals.json", person_a_batch())
                ad.editor_handoff(run_dir, "proposal-topic-1", "alltagstauglich")
                c = ad.run_person_c(run_dir, make_image=False)
                self.assertEqual(len(c["recipes"]), 2)
                self.assertTrue(c["review"])
                self.assertEqual(c["log"]["proposal_id"], "proposal-topic-1")
                self.assertEqual(c["log"]["steering_notes"], ["alltagstauglich"])
                self.assertEqual(set(c["cards"]), {"r1", "r2"})
                self.assertEqual(ad.page_count(c["cards"]["r1"]), 1)
                run = ad.load_run(run_dir)
                self.assertIn("person_c_seconds", run["timings"])
        finally:
            os.environ.pop("OFFLINE", None)


class Config(unittest.TestCase):
    def test_c_config_points_at_tracked_data(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ad.c_config(Path(d))
        self.assertTrue(Path(cfg.nutrition_csv).is_file())
        self.assertTrue(str(cfg.nutrition_csv).endswith(".csv"))
        self.assertTrue(Path(cfg.template_html).is_file())
        self.assertEqual(Path(cfg.output_dir).name, "c")

    def test_split_notes(self):
        self.assertEqual(ad._split_notes(" a; b \n\n c "), ["a", "b", "c"])
        self.assertEqual(ad._split_notes(""), [])

    def test_sparkline_and_google_signal(self):
        p = person_a_batch()["proposals"][0]
        s = ad.sparkline(p)
        self.assertEqual(len(s), 14)
        self.assertEqual(s[-1], ("2026-11-18", 118))
        self.assertIn("<svg", ui.sparkline_svg([v for _, v in s]))
        self.assertIn("no series", ui.sparkline_svg([]))
        g = ad.google_signal(p)
        self.assertEqual(g["interest"], 49)
        self.assertEqual(g["increase"], "90 %")


class Impact(unittest.TestCase):
    def test_metrics_are_measured_from_the_log_only(self):
        c = {"log": {"events": [{"t": 0.0, "stage": "selection", "event": "x"}, {"t": 2.0, "stage": "recipe", "event": "generated"},
                                {"t": 5.5, "stage": "review", "event": "r1 pass"}, {"t": 9.0, "stage": "image", "event": "r1 generated"}]},
             "review": [{"recipe_id": "r1", "criteria": {"title": {"pass": True, "issues": []}, "tbsp_tsp": {"pass": False, "issues": ["1 EL Zimt", "Hinweis: x"]}}, "extras": {}},
                        {"recipe_id": "r1", "criteria": {"title": {"pass": True, "issues": []}, "tbsp_tsp": {"pass": True, "issues": []}}, "extras": {}}],
             "recipes": [{"id": "r1", "history": [{"version": 2, "changes": [{"criterion": "tbsp_tsp", "change": "1 TL"}]}],
                          "image": {"verification": {"score": 9, "retried": False, "model": "m"}}},
                         {"id": "r2", "history": [], "image": {"verification": "nicht verfügbar"}}],
             "nutrition": {"r1": {"coverage": {"ingredients_calculated": 8, "ingredients_needing_calc": 9, "share": 0.89, "quality": "mittel"},
                                  "per_serving": {"kcal": 500}, "ingredients": [{"match": "closest_category"}, {"match": "exact"}]}}}
        m = ad.impact_metrics(c, {"person_a_seconds": 31.2})
        self.assertEqual(m["seconds_per_stage"], {"selection": 0.0, "recipe": 2.0, "review": 3.5, "image": 3.5})
        self.assertEqual(m["review_rounds"], 2)
        self.assertEqual(m["issues_caught"], 1)                 # "Hinweis" warnings are not issues
        self.assertEqual(m["corrections"], 1)
        self.assertEqual(m["image_scores"]["r1"]["score"], 9)
        self.assertIsNone(m["image_scores"]["r2"]["score"])
        self.assertEqual(m["nutrition"]["r1"]["closest"], 1)
        self.assertEqual(m["person_a_seconds"], 31.2)
        self.assertEqual(ad.impact_metrics(None)["issues_caught"], 0)


class DemoCache(unittest.TestCase):
    def _fake_run(self, d: Path) -> Path:
        run_dir = d / "20260101_000000"
        ad._write(run_dir / "proposals.json", person_a_batch())
        ad._write(run_dir / "selection.json", {"picks": 1, "selected_ids": ["proposal-topic-1"], "steering_notes": []})
        (run_dir / "editor_audit.jsonl").write_text('{"event": "editor_selected"}\n', encoding="utf-8")
        ad._write(run_dir / "timings.json", {"person_a_seconds": 1.0})
        (run_dir / "c" / "img").mkdir(parents=True)
        (run_dir / "c" / "cards").mkdir(parents=True)
        (run_dir / "c" / "img" / "r1.jpg").write_bytes(b"\xff\xd8jpeg")
        (run_dir / "c" / "cards" / "r1.html").write_text('<div class="page">x</div>', encoding="utf-8")
        (run_dir / "c" / "cards" / "das_schmeckt_rezepte.html").write_text('<div class="page">x</div>', encoding="utf-8")
        ad._write(run_dir / "c" / "recipes.json", [{"id": "r1", "title": "T", "image": {"path": str(run_dir / "c" / "img" / "r1.jpg"), "status": "generated"}}])
        ad._write(run_dir / "c" / "review.json", [])
        ad._write(run_dir / "c" / "nutrition.json", [{"recipe_id": "r1", "coverage": {}, "per_serving": {}}])
        ad._write(run_dir / "c" / "stage_c_log.json", {"events": [{"t": 0, "stage": "render", "event": "cards written", "files": [str(run_dir / "c" / "cards" / "r1.html")]}]})
        return run_dir

    def test_round_trip_relative_paths_and_no_machine_paths(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._fake_run(Path(d))
            dest = ad.save_demo_cache(run_dir, Path(d) / "demo")
            recipes = json.loads((dest / "c" / "recipes.json").read_text(encoding="utf-8"))
            self.assertEqual(recipes[0]["image"]["path"], "c/img/r1.jpg")
            log = (dest / "c" / "stage_c_log.json").read_text(encoding="utf-8")
            self.assertNotIn(str(run_dir), log)
            run = ad.load_run(dest, "demo")
            self.assertEqual(run["mode"], "demo")
            self.assertTrue(run["c"]["recipes"][0]["image"]["resolved_path"].endswith("r1.jpg"))
            self.assertEqual(ad.page_count(run["c"]["combined"]), 1)
            self.assertTrue((dest / "META.json").is_file())

    def test_key_shaped_strings_block_the_cache(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._fake_run(Path(d))
            ad._write(run_dir / "c" / "review.json", [{"note": "sk-" + "A" * 30}])
            with self.assertRaises(ValueError):
                ad.save_demo_cache(run_dir, Path(d) / "demo")
            self.assertFalse((Path(d) / "demo").exists())

    def test_shipped_demo_cache_has_no_keys(self):
        if not ad.demo_available():
            self.skipTest("no demo cache committed yet")
        self.assertEqual(ad.scan_for_keys([p for p in ad.DEMO_DIR.rglob("*") if p.is_file()]), [])


@unittest.skipUnless(ad.demo_available(), "needs the committed demo cache")
class PageInDemoMode(unittest.TestCase):
    """The real page, driven like a user: demo toggle, then every step, checking what each one shows."""
    def _page(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "prototype" / "app.py"), default_timeout=120)
        at.run()
        at.toggle(key="tgl_demo").set_value(True).run()
        self.assertFalse(at.exception, at.exception)
        return at

    def _texts(self, at) -> str:
        """Everything a user can read: markdown, captions and the expander/tab labels."""
        return ("\n".join(m.value for m in at.markdown) + "\n" + "\n".join(c.value for c in at.caption) + "\n"
                + "\n".join(e.label for e in at.expander) + "\n" + "\n".join(t.label for t in at.tabs))

    def _goto(self, at, n):
        at.radio(key="nav").set_value(n).run()
        self.assertFalse(at.exception, at.exception)
        return at

    def test_every_step_renders_the_cached_run(self):
        at = self._page()
        demo = ad.load_run(ad.DEMO_DIR, "demo")
        txt = self._texts(at)
        self.assertIn("Google Trends", txt)
        self.assertIn("Wikipedia pageviews", txt)
        self._goto(at, 2)
        txt = self._texts(at)
        for p in demo["proposals"]["proposals"]:
            self.assertIn(p["title"].split()[0], txt)
        self.assertTrue(any("rejected" in e.label for e in at.expander))
        self._goto(at, 3)
        self.assertIn("Selected", self._texts(at))
        self.assertTrue(at.radio(key="pick").disabled)
        self._goto(at, 4)
        txt = self._texts(at)
        for r in demo["c"]["recipes"]:
            self.assertIn(r["title"], txt)
        self.assertIn("Zutaten", txt)
        self.assertTrue(all(b.disabled for b in at.button if str(b.key).startswith("btn_sendback")))
        self._goto(at, 5)
        txt = self._texts(at)
        self.assertIn("Round 1", txt)
        self.assertIn("Nutrition per serving", txt)
        self.assertIn("Image verification", txt)
        self._goto(at, 6)
        txt = self._texts(at)
        self.assertIn("Seconds per stage", txt)
        self.assertIn("pages per card", txt)
        self.assertTrue(any(b.label.startswith("Download") for b in at.get("download_button")))

    def test_live_buttons_are_not_offered_in_demo_mode(self):
        at = self._page()
        self.assertFalse(any(b.key == "btn_run_a" for b in at.button))
        self._goto(at, 4)
        self.assertFalse(any(b.key == "btn_run_c" for b in at.button))


if __name__ == "__main__":
    unittest.main()
