import csv
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from editor import trends
from editor.agents import propose_with_trends
from editor.archive import load_archive
from editor.contract import check_proposals
from editor.display import trend_summary, wikimedia_summary
from editor.workflow import EditorWorkflow

REAL = Path(__file__).resolve().parents[2] / "data" / "trends"
HEAD = ["Signal type", "Source kind", "Google term", "Search interest", "Increase percent", "Wikipedia article",
        "Mapping method", "Review required", "Previous period start", "Previous period end", "Previous 7d views",
        "Latest period start", "Latest period end", "Latest 7d views", "Change percent", "Status"]
COLS = "ABCDEFGHIJKLMNOP"


def write_csv(path, key, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow([key, "search interest", "increase percent"])
        w.writerows(rows)


def write_xlsx(path, summary, daily=()):
    """Change percent is stored as a FRACTION like the real file (0.74 = +74%). summary: dicts keyed by HEAD names; builds a minimal workbook with sparse cells and shared strings."""
    strings, rows_xml = [], []

    def sst(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def sheet(rows):
        out = []
        for i, row in enumerate(rows, 1):
            cells = "".join(f'<c r="{col}{i}" t="s"><v>{sst(str(v))}</v></c>' for col, v in row if v is not None)
            out.append(f'<row r="{i}">{cells}</row>')
        return ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(out) +
                "</sheetData></worksheet>")
    s2 = [list(zip(COLS, HEAD))] + [[(c, r.get(h)) for c, h in zip(COLS, HEAD)] for r in summary]
    s3 = [[("A", "Wikipedia article"), ("B", "Date"), ("C", "Views"), ("D", "Status")]] + [
        [("A", a), ("B", d + "T00:00:00.000Z"), ("C", v), ("D", "ok")] for a, d, v in daily]
    s1 = [[("B", "Overview")]]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet(s1))
        zf.writestr("xl/worksheets/sheet2.xml", sheet(s2))
        zf.writestr("xl/worksheets/sheet3.xml", sheet(s3))
        zf.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
                    "".join(f"<si><t>{escape(t)}</t></si>" for t in strings) + "</sst>")
        zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                    '<sheet name="Overview" sheetId="1" r:id="rId1"/><sheet name="Topic summary" sheetId="2" r:id="rId2"/>'
                    '<sheet name="Daily pageviews" sheetId="3" r:id="rId3"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                    '<Relationship Id="rId3" Target="worksheets/sheet3.xml"/></Relationships>')


def wrow(signal, kind, term, article, prev, latest, change, *, review="0", mapping="curated", status="ok", interest="1", inc="10 %"):
    return {"Signal type": signal, "Source kind": kind, "Google term": term, "Search interest": interest, "Increase percent": inc,
            "Wikipedia article": article, "Mapping method": mapping, "Review required": review, "Previous 7d views": str(prev),
            "Latest 7d views": str(latest), "Change percent": str(change), "Status": status}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        (self.base / "google-trends").mkdir()
        (self.base / "wikimedia").mkdir()

    def build(self, rising_q=(), rising_t=(), top_q=(), top_t=(), wiki=(), daily=()):
        g = self.base / "google-trends"
        write_csv(g / "searched_with_rising-searches_queries_DE_x.csv", "query", rising_q)
        write_csv(g / "searched_with_rising-searches_topics_DE_x.csv", "topic", rising_t)
        write_csv(g / "searched_with_top-searches_queries_DE_x.csv", "query", top_q)
        write_csv(g / "searched_with_top-searches_topics_DE_x.csv", "topic", top_t)
        write_xlsx(self.base / "wikimedia" / "Wikimedia_Pageviews_Fallback_x.xlsx", list(wiki), list(daily))
        return trends.load_trends(self.base)


class ParseTest(unittest.TestCase):
    def test_percent_parsing(self):
        self.assertEqual([trends.parse_pct(x) for x in ("1.450 %", "-30 %", "950 %", "+5%", "0 %", "", "Breakout", None)],
                         [1450, -30, 950, 5, 0, None, None, None][:8])

    def test_clean_term_removes_generic_words_only(self):
        self.assertEqual(trends.clean_term("grünkohl rezept klassisch"), "grünkohl klassisch")
        self.assertEqual(trends.clean_term("Curly kale (Vegetable)"), "Curly kale")


class LoadTest(Base):
    def test_missing_inputs_raise_clear_errors(self):
        with self.assertRaises(FileNotFoundError):
            trends.load_trends(self.base / "nope")
        with self.assertRaises(FileNotFoundError):
            trends.load_trends(self.base)                              # dirs exist but no CSV
        write_csv(self.base / "google-trends" / "searched_with_rising-searches_queries_DE_x.csv", "query", [])
        with self.assertRaises(ValueError):
            trends.load_trends(self.base)                              # CSV without rows

    def test_unreadable_wikimedia_snapshot_degrades_to_google_only(self):
        write_csv(self.base / "google-trends" / "searched_with_rising-searches_queries_DE_x.csv", "query", [("linsensuppe rezept", 3, "40 %")])
        (self.base / "wikimedia" / "snap.xlsx").write_text("not a zip")
        data = trends.load_trends(self.base)
        self.assertTrue(any("unreadable" in n for n in data.notes))
        accepted, _ = trends.select(data)
        self.assertEqual(accepted[0][1]["single_source"], True)

    def test_variants_merge_by_article_and_review_flagged_mapping_is_not_used(self):
        data = self.build(
            rising_q=[("rosenkohl rezept", 0, "70 %"), ("rosenkohl rezepte", 0, "70 %"), ("mystery rezept", 2, "300 %")],
            rising_t=[("Brussels sprout", 28, "70 %")],
            wiki=[wrow("rising", "query", "rosenkohl rezept", "Rosenkohl", 100, 150, 0.5),
                  wrow("rising", "query", "rosenkohl rezepte", "Rosenkohl", 100, 150, 0.5),
                  wrow("rising", "topic", "Brussels sprout", "Rosenkohl", 100, 150, 0.5),
                  wrow("rising", "query", "mystery rezept", "Wrong Article", 5, 500, 99.0, review="1", mapping="search_result_review")])
        by = {g.topic: g for g in data.groups}
        self.assertEqual(len(by["Rosenkohl"].signals), 3)
        self.assertEqual(by["Rosenkohl"].wiki.views_latest, 150)
        self.assertIn("Mystery", by)                                   # fell back to the Google term, article ignored
        self.assertNotIn("Wrong Article", by)
        self.assertIsNone(by["Mystery"].wiki)

    def test_daily_points_come_from_the_snapshot(self):
        data = self.build(rising_q=[("linsensuppe rezept", 3, "40 %")],
                          wiki=[wrow("rising", "query", "linsensuppe rezept", "Linsensuppe", 10, 20, 1.0)],
                          daily=[("Linsensuppe", "2026-11-04", 7), ("Linsensuppe", "2026-11-05", 9), ("Other", "2026-11-05", 1)])
        g = data.groups[0]
        self.assertEqual([p["value"] for p in g.points], [7, 9])
        block = trends.trend_block(g, trends.score_group(g))
        self.assertEqual(block["sparkline"], [7, 9])


class SelectionTest(Base):
    def test_eligibility_and_honest_no_decisions(self):
        data = self.build(
            rising_q=[("grünkohl rezept", 23, "200 %"), ("thermomix rezepte", 5, "50 %")],
            rising_t=[("Spinach (Vegetable)", 26, "20 %")],                          # topic-only: no recipe-intent query
            top_q=[("kürbissuppe rezept", 1, "-30 %"), ("waffeln rezept", 1, "0 %")],
            wiki=[])
        accepted, rejected = trends.select(data)
        self.assertEqual([g.topic for g, _ in accepted], ["Grünkohl"])
        reasons = {r["topic"]: r["reason"] for r in rejected}
        self.assertIn("Declining", reasons["Kürbissuppe"])
        self.assertIn("-30", reasons["Kürbissuppe"])
        self.assertIn("No rising signal", reasons["Waffeln"])
        self.assertIn("Topic-only", reasons["Spinach"])
        self.assertNotIn("Thermomix", reasons)                                       # generic/brand/appliance terms are dropped

    def test_score_formula_volume_damping_and_bounds(self):
        data = self.build(rising_q=[("a rezept", 0, "1.450 %"), ("b rezept", 23, "1.450 %")],
                          wiki=[wrow("rising", "query", "b rezept", "B", 100, 500, 4.0)])
        comp = {g.topic: trends.score_group(g) for g in data.groups}
        low, high = comp["A"], comp["B"]
        self.assertLess(low["google"], 30)                                           # interest 0 -> damped (factor 0.2)
        self.assertEqual(low["interest_factor_google"], 0.2)
        self.assertTrue(low["single_source"])
        self.assertAlmostEqual(high["google"], 100 * math.log10(1451) / math.log10(1501) * 1.0, places=1)
        self.assertEqual(high["views_factor_wikipedia"], 1.0)
        self.assertAlmostEqual(high["wikipedia"], 100 * math.log10(401) / math.log10(501), places=1)
        self.assertAlmostEqual(high["score"], round(0.5 * high["google"] + 0.5 * high["wikipedia"], 1), places=1)
        for c in comp.values():
            self.assertTrue(0 <= c["score"] <= 100)

    def test_family_cap_limit_exclusion_and_determinism(self):
        cookies = [("plätzchen rezept", 20, "500 %"), ("spitzbuben rezept", 19, "490 %"), ("kekse rezept", 18, "480 %"),
                   ("zimtsterne rezept", 17, "470 %")]
        data = self.build(rising_q=cookies + [("linsensuppe rezept", 15, "40 %")])
        accepted, rejected = trends.select(data, 5)
        topics = [g.topic for g, _ in accepted]
        self.assertEqual(sum(1 for t in topics if t in ("Plätzchen", "Spitzbuben", "Kekse", "Zimtsterne")), trends.FAMILY_CAP)
        self.assertIn("Linsensuppe", topics)
        self.assertTrue(any("Family cap" in r["reason"] for r in rejected))
        self.assertEqual(accepted, trends.select(data, 5)[0])                       # deterministic
        again, _ = trends.select(data, 5, exclude=set(topics))
        self.assertFalse(set(topics) & {g.topic for g, _ in again})
        self.assertEqual(len(trends.select(data, 2)[0]), 2)

    # ---- review finding 1: growth and interest must come from the SAME row
    def test_google_score_never_mixes_growth_and_interest_across_rows(self):
        data = self.build(
            rising_q=[("engelsaugen rezept", 0, "1.450 %")],                # strong growth, interest index 0
            top_q=[("husarenkrapferl rezept", 100, "-5 %")],                # different row, index 100 ...
            wiki=[wrow("rising", "query", "engelsaugen rezept", "Husarenkrapferl", 46, 80, 0.74),    # ... same article => same group
                  wrow("top", "query", "husarenkrapferl rezept", "Husarenkrapferl", 46, 80, 0.74)])
        group = data.groups[0]
        self.assertEqual(len(group.signals), 2)
        comp = trends.score_group(group)
        self.assertEqual(comp["search_interest_index"], 0)                  # taken from the rising row, not from the 100 row
        self.assertEqual(comp["interest_factor_google"], 0.2)
        self.assertAlmostEqual(comp["google"], 100 * math.log10(1451) / math.log10(1501) * 0.2, places=1)
        self.assertLess(comp["google"], 25)
        self.assertEqual(comp["best_term"], "engelsaugen rezept")

    def test_strongest_damped_row_wins_not_the_largest_increase(self):
        data = self.build(rising_q=[("x rezept", 0, "1.450 %"), ("x rezepte", 40, "100 %"), ("x klassisch rezept", 90, "-10 %")])
        comp = trends.score_group(data.groups[0])
        self.assertEqual(comp["best_term"], "x rezepte")                    # +100% at index 40 beats +1450% at index 0
        self.assertEqual((comp["rising_increase_pct"], comp["search_interest_index"]), (100, 40))
        self.assertEqual(comp["interest_factor_google"], 1.0)

    def test_declining_or_flat_rows_never_feed_the_google_score(self):
        data = self.build(rising_q=[("y rezept", 80, "0 %")], top_q=[("y rezept", 100, "-30 %")])
        comp = trends.score_group(data.groups[0])
        self.assertEqual((comp["google"], comp["rising_increase_pct"], comp["best_term"]), (0.0, 0, None))

    def test_wording_calls_it_an_index_not_a_volume(self):
        data = self.build(rising_q=[("linsensuppe rezept", 15, "40 %")])
        g = data.groups[0]
        block = trends.trend_block(g, trends.score_group(g))
        self.assertIn("search-interest index", block["why_relevant"])
        text = trend_summary({"trend": block})
        self.assertIn("search-interest index", text)
        self.assertIn("not a search volume", text)
        self.assertNotIn("volume factor", text)

    # ---- review finding 2: missing / unusable Wikimedia evidence stays distinct and is never credited
    def wiki_block(self, rows, **build_kw):
        data = self.build(rising_q=[("linsensuppe rezept", 15, "40 %")], wiki=rows, **build_kw)
        g = data.groups[0]
        return trends.trend_block(g, trends.score_group(g)), data

    def test_workbook_missing_is_unavailable_and_not_a_source(self):
        write_csv(self.base / "google-trends" / "searched_with_rising-searches_queries_DE_x.csv", "query", [("linsensuppe rezept", 15, "40 %")])
        data = trends.load_trends(self.base)                                  # no xlsx at all
        block = trends.trend_block(data.groups[0], trends.score_group(data.groups[0]))
        self.assertEqual(data.wiki_state, "missing")
        self.assertEqual(block["wikimedia"]["status"], "unavailable")
        self.assertIn("not found", block["wikimedia"]["error"])
        self.assertEqual(len(block["sources"]), 1)
        self.assertFalse(any("Wikimedia" in x for x in block["sources"]))

    def test_workbook_unreadable_is_unavailable_with_its_own_reason(self):
        write_csv(self.base / "google-trends" / "searched_with_rising-searches_queries_DE_x.csv", "query", [("linsensuppe rezept", 15, "40 %")])
        (self.base / "wikimedia" / "snap.xlsx").write_text("not a zip")
        data = trends.load_trends(self.base)
        block = trends.trend_block(data.groups[0], trends.score_group(data.groups[0]))
        self.assertEqual(data.wiki_state, "unreadable")
        self.assertEqual((block["wikimedia"]["status"], "could not be read" in block["wikimedia"]["reason"]), ("unavailable", True))
        self.assertEqual(len(block["sources"]), 1)

    def test_no_mapping_review_flag_and_no_data_are_three_different_states(self):
        no_map, _ = self.wiki_block([])
        flagged, _ = self.wiki_block([wrow("rising", "query", "linsensuppe rezept", "Linsensuppe", 10, 20, 1.0,
                                            review="1", mapping="search_result_review")])
        nodata, _ = self.wiki_block([wrow("rising", "query", "linsensuppe rezept", "Linsensuppe", 10, 20, 1.0, status="missing")])
        self.assertEqual(no_map["wikimedia"]["status"], "no_article_found")
        self.assertIn("no Wikipedia article is mapped", no_map["wikimedia"]["reason"])
        self.assertEqual(flagged["wikimedia"]["status"], "no_article_found")
        self.assertIn("flagged for review", flagged["wikimedia"]["reason"])
        self.assertEqual(nodata["wikimedia"]["status"], "no_data")
        self.assertIn("no usable page views", nodata["wikimedia"]["reason"])
        for block in (no_map, flagged, nodata):
            self.assertEqual(len(block["sources"]), 1)                        # the snapshot contributed nothing
            self.assertEqual(wikimedia_summary({"trend": block})[0], "warn")
            self.assertIn("could NOT be checked", wikimedia_summary({"trend": block})[1])
            self.assertIsNone(block["components"]["wikipedia"])
            self.assertTrue(block["components"]["single_source"])

    def test_snapshot_is_credited_only_when_it_contributes(self):
        ok, _ = self.wiki_block([wrow("rising", "query", "linsensuppe rezept", "Linsensuppe", 10, 20, 1.0)])
        self.assertEqual(ok["wikimedia"]["status"], "available")
        self.assertEqual(ok["sources"][1], trends.SNAPSHOT_LABEL)
        self.assertFalse(ok["components"]["single_source"])

    def test_reason_texts_reach_the_ui_summary(self):
        _, _ = self.wiki_block([])
        block, _ = self.wiki_block([wrow("rising", "query", "linsensuppe rezept", "Linsensuppe", 10, 20, 1.0, review="1")])
        self.assertIn("flagged for review", wikimedia_summary({"trend": block})[1])

    def test_trend_block_is_honest_about_low_volume_and_single_source(self):
        data = self.build(rising_q=[("engelsaugen rezept", 0, "1.450 %")])
        g = data.groups[0]
        block = trends.trend_block(g, trends.score_group(g))
        self.assertIn("unreliable", block["why_relevant"])
        self.assertIn("not a volume", block["why_relevant"])
        self.assertNotIn("absolute", block["why_relevant"])
        self.assertIn("single source", block["why_relevant"])
        self.assertEqual(block["wikimedia"]["status"], "no_article_found")
        self.assertEqual(wikimedia_summary({"trend": block})[0], "warn")
        self.assertIn("single source", trend_summary({"trend": block}))


class ProposalTest(Base):
    def make(self, archive=None):
        self.build(rising_q=[("linsensuppe rezept", 15, "40 %"), ("grünkohl rezept", 23, "200 %"), ("tiramisu rezept", 12, "20 %")],
                   wiki=[wrow("rising", "query", "grünkohl rezept", "Grünkohl", 100, 300, 2.0)])
        return propose_with_trends(self.base, archive)

    def test_proposals_follow_the_contract_and_stay_honest_about_what_is_not_real(self):
        accepted, rejected = self.make()(set(), 5)
        check_proposals((accepted, rejected))
        self.assertEqual([p["rank"] for p in accepted], [1, 2, 3])
        self.assertEqual(accepted[0]["topic"], "Grünkohl")
        for p in accepted:
            self.assertIsNone(p["brand_fit"]["score"])
            self.assertIn("Not assessed", p["brand_fit"]["reasoning"])
            self.assertEqual(p["recipe_ideas"], [])
            self.assertEqual(p["archive"]["match_status"], "archive_unavailable")   # no archive given: stated, not invented
        self.assertEqual(len({p["id"] for p in accepted}), 3)

    def test_works_inside_the_workflow_including_reject_all(self):
        with tempfile.TemporaryDirectory() as d:
            from editor.agents import Agents
            wf = EditorWorkflow(Agents(propose=self.make()), Path(d) / "a.jsonl", Path(d) / "cards")
            wf.start()
            first = {p["topic"] for p in wf.proposals}
            self.assertEqual(wf.stage, "proposals")
            from editor.workflow import WorkflowError
            with self.assertRaises(WorkflowError):                                    # only 3 topics exist: next round is empty
                wf.reject_all("none fit")
            self.assertEqual(first, {"Grünkohl", "Linsensuppe", "Tiramisu"})

    def test_missing_trend_data_raises_instead_of_inventing_topics(self):
        with self.assertRaises(FileNotFoundError):
            propose_with_trends(self.base / "missing")


@unittest.skipUnless((REAL / "google-trends").is_dir(), "provided trend data not present")
class RealDataSmokeTest(unittest.TestCase):
    def test_real_provided_files(self):
        data = trends.load_trends(REAL)
        accepted, rejected = trends.select(data, 5)
        self.assertEqual(len(accepted), 5)
        self.assertEqual(len({g.topic for g, _ in accepted}), 5)
        self.assertTrue(all(0 <= c["score"] <= 100 for _g, c in accepted))
        self.assertTrue(any("Declining" in r["reason"] for r in rejected))
        self.assertFalse(any(g.topic.casefold() in trends.NON_DISH for g, _ in accepted))
        husar = next(g for g in data.groups if g.topic == "Husarenkrapferl")       # xlsx row: 46 -> 80 views, fraction 0.739
        self.assertAlmostEqual(husar.wiki.change_pct, 73.9, places=1)
        self.assertEqual((husar.wiki.views_prev, husar.wiki.views_latest), (46, 80))
        self.assertEqual(trends.parse_pct("1.450 %"), 1450)
        proposals, _ = propose_with_trends(REAL, load_archive(None))(set(), 5)
        check_proposals((proposals, []))


if __name__ == "__main__":
    unittest.main()
