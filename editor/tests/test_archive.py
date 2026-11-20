import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from editor import archive as arc
from editor.agents import Agents, propose_with_archive
from editor.archive import Archive, load_archive, lookup
from editor.display import archive_summary

XML = ('<?xml version="1.0" encoding="UTF-8"?><document xmlns="http://www.digicol.com/xmlns/dcx" id="{id}" '
       'dcx-version="6.3.1" version="1.0"><created>2020-08-01T00:00:00+02:00</created><modified>2021-01-01T00:00:00+01:00</modified>'
       '<head><Headline>{title}</Headline>{sub}{ings}</head><body/></document>')


def recipe_xml(rid, title, ingredients=(), subtitle=""):
    """ingredients: (position, plural or None, prefix or None)"""
    rows = "".join('<CustomRecipeIngredient position="%d"%s%s amount="1" unit="g"/>' % (
        pos, f' plural="{pl}"' if pl else "", f' prefix="{pf}"' if pf else "") for pos, pl, pf in ingredients)
    return XML.format(id=rid, title=title, sub=f"<SubHeadline>{subtitle}</SubHeadline>" if subtitle else "",
                      ings=f"<CustomRecipeIngredients>{rows}</CustomRecipeIngredients>")


def make_zip(dirpath, recipes, extra=None, manifest=True, category="Suppen und Eintöpfe"):
    """recipes: [(id, title, ingredients, subtitle)] -> path of a synthetic export ZIP."""
    path = Path(dirpath) / "export.zip"
    entries = []
    with zipfile.ZipFile(path, "w") as zf:
        for rec in recipes:
            rid, title, ings, sub = rec[:4]
            name = f"rezepte_export/{rid}.xml"
            zf.writestr(name, recipe_xml(rid, title, ings, sub))
            entries.append({"id": rid, "titel": title, "datei": name, "hauptkategorie": rec[4] if len(rec) > 4 else category})
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
        if manifest:
            zf.writestr("auswahl_manifest.json", json.dumps({"rezepte": entries + [
                {"id": "x", "titel": "t", "datei": n, "hauptkategorie": "c"} for n in (extra or {})]}))
    return path


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def archive(self, recipes, **kw):
        return load_archive(make_zip(self.dir, recipes, **kw))

    def test_ranked_matches_title_before_ingredient_and_weak_hits_are_not_credible(self):
        a = self.archive([
            ("1", "Pastinaken-Suppe", [(1, "Pastinaken", None)], ""),
            ("2", "Ofengemüse", [(1, "Pastinaken", None), (2, "Möhren", None)], ""),                # main ingredient only
            ("3", "Pastinakensalat", [(5, "Rucola", None)], ""),                                     # compound title
            ("4", "Eintopf", [(1, "Kartoffeln", None)] + [(i, "Salz", None) for i in range(2, 8)] + [(8, "Pastinaken", None)], ""),  # weak
            ("5", "Apfelkuchen", [(1, "Äpfel", None)], ""),
        ])
        block = lookup(a, "Pastinake")
        self.assertEqual(block["match_status"], "matches_found")
        self.assertEqual([r["id"] for r in block["similar_recipes"]], ["1", "3", "2"])           # title hits first, alphabetical tie
        self.assertEqual(block["match_count"], 3)                                                # recipe 4 is not credible
        self.assertIn("title contains", block["similar_recipes"][0]["why"])
        self.assertIn("main ingredient (position 1)", block["similar_recipes"][2]["why"])

    def test_at_most_three_returned_but_all_are_counted_and_deterministic(self):
        a = self.archive([(str(i), f"Linsen-Gericht {i:02d}", [], "") for i in range(7)])
        first, second = lookup(a, "Linsen"), lookup(a, "Linsen")
        self.assertEqual(len(first["similar_recipes"]), 3)
        self.assertEqual(first["match_count"], 7)
        self.assertEqual(first, second)
        self.assertEqual(first["repetition_risk"], "not_assessed")      # many matches show coverage, not repetition

    def test_no_credible_match_is_not_reported_as_low_risk_or_proof(self):
        a = self.archive([("1", "Apfelkuchen", [(1, "Äpfel", None)], "")])
        block = lookup(a, "Pastinake")
        self.assertEqual(block["match_status"], "no_match_found")
        self.assertEqual(block["similar_recipes"], [])
        self.assertEqual(block["repetition_risk"], "not_assessed")
        self.assertIn("Hypothesis", block["content_gap"])
        self.assertIn("selection", block["content_gap"])
        self.assertIn("5,000 of 81,798", block["assumption"])

    def test_short_terms_do_not_match_inside_other_words(self):
        a = self.archive([("1", "Preiselbeer-Kuchen", [], ""), ("2", "Reispfanne", [(1, "Reis", None)], "")])
        self.assertEqual([r["id"] for r in lookup(a, "Reis")["similar_recipes"]], ["2"])

    def test_multi_word_topics_need_all_words_or_the_compound(self):
        a = self.archive([
            ("1", "Ofen-Kartoffeln", [(1, "Kartoffeln", None)], ""),                      # only 'Ofen'
            ("2", "Feta-Salat", [(1, "Feta", None)], ""),                                  # only 'Feta'
            ("3", "Feta aus dem Ofen", [(1, "Feta", None)], ""),                           # both words
            ("4", "Ofenfeta mit Tomaten", [(1, "Tomaten", None)], ""),                     # compound spelling
            ("5", "Gebackener Fetakäse", [(1, "Feta", None), (2, "Honig", None)], "")])
        ids = [r["id"] for r in lookup(a, "Ofen-Feta")["similar_recipes"]]
        self.assertEqual(sorted(ids), ["3", "4"])

    def test_umlauts_and_plurals(self):
        a = self.archive([("1", "Kürbissuppe", [], ""), ("2", "Linsen-Dal", [], "")])
        self.assertEqual([r["id"] for r in lookup(a, "Kürbis")["similar_recipes"]], ["1"])
        self.assertEqual([r["id"] for r in lookup(a, "Linse")["similar_recipes"]], ["2"])

    def test_unnamed_ingredients_are_unknown_not_matches(self):
        a = self.archive([("1", "Eintopf", [(1, None, None), (2, "Salz", None)], "")])
        self.assertEqual(a.recipes[0].unnamed, 1)
        self.assertEqual(lookup(a, "Pastinake")["match_status"], "no_match_found")
        self.assertIn("without a readable name", lookup(a, "Pastinake")["assumption"])

    def test_publication_date_is_never_taken_from_cms_timestamps(self):
        a = self.archive([("1", "Pastinaken-Suppe", [], "")])      # XML has <created>2020-08...</created>
        block = lookup(a, "Pastinake")
        self.assertIsNone(block["last_published"])
        self.assertIsNone(block["similar_recipes"][0]["publication_date"])
        self.assertIn("Publication date unavailable", block["similar_recipes"][0]["publication_note"])
        self.assertNotIn("2020", json.dumps(block))
        self.assertIn("Publication date unavailable", archive_summary({"archive": block})[1])

    def test_repetition_risk_is_never_derived_from_topic_match_counts(self):
        for n in (0, 1, 8, 60):
            a = self.archive([(str(i), f"Kürbis-Gericht {i:02d}", [], "") for i in range(n)] + [("x", "Apfelkuchen", [], "")])
            self.assertEqual(lookup(a, "Kürbis")["repetition_risk"], "not_assessed")
        text = archive_summary({"archive": lookup(a, "Kürbis")})[1]
        self.assertIn("not assessed", text)
        self.assertIn("topic coverage", text)
        self.assertNotIn("high", text.casefold().replace("highlight", ""))

    def test_category_summary_never_claims_other_categories_are_empty(self):
        cats = ["Suppen", "Salate", "Pasta", "Desserts", "Brot", "Fisch"]
        a = self.archive([(str(i), f"Pastinaken-Gericht {i}", [], "", cats[i % 6]) for i in range(12)])
        gap = lookup(a, "Pastinake")["content_gap"]
        self.assertIn("6 categories", gap)
        self.assertIn("top 4 of 6 shown", gap)
        self.assertNotIn("Other categories show none", gap)
        self.assertNotIn("gap", gap.replace("not a gap analysis", ""))
        one = lookup(self.archive([("1", "Pastinaken-Suppe", [], "")]), "Pastinake")["content_gap"]
        self.assertIn("1 category", one)
        self.assertNotIn("shown", one)

    # ---- unavailable archive
    def test_missing_or_broken_archive_never_raises(self):
        broken = Path(self.dir) / "notzip.zip"
        broken.write_text("hello")
        nomanifest = make_zip(self.dir, [("1", "A", [], "")], manifest=False)
        for arg, reason in ((None, "no archive path"), (Path(self.dir) / "nope.zip", "not found"),
                            (broken, "could not be read"), (nomanifest, "manifest")):
            a = load_archive(arg)
            self.assertFalse(a.available)
            block = lookup(a, "Pastinake")
            self.assertEqual(block["match_status"], "archive_unavailable")
            self.assertEqual(block["repetition_risk"], "not_assessed")
            self.assertIn(reason, block["assumption"])
            level, text = archive_summary({"archive": block})
            self.assertEqual(level, "warn")
            self.assertIn("could NOT be checked", text)

    def test_hostile_or_broken_members_are_skipped_and_counted(self):
        a = self.archive([("1", "Pastinaken-Suppe", [], "")], extra={
            "rezepte_export/bad.xml": "<document><head>",                                         # not parseable
            "rezepte_export/dtd.xml": '<!DOCTYPE x [<!ENTITY a "b">]><document/>',                # entity tricks refused
            "rezepte_export/big.xml": "<d>" + "x" * (arc.MAX_XML_BYTES + 1) + "</d>"})
        self.assertEqual(len(a.recipes), 1)
        self.assertEqual(a.skipped, 3)

    def test_malformed_manifest_shapes_become_unavailable_never_a_crash(self):
        shapes = ["[]", '"text"', "42", "null", '{"rezepte": "x"}', '{"rezepte": {"a": 1}}', "{}",
                  '{"rezepte": [1, "a", null, [], {"datei": 5}, {"datei": null}]}',
                  '{"rezepte": [{"datei": "rezepte_export/1.xml", "titel": 7, "id": 3, "hauptkategorie": ["x"]}]}']
        for i, shape in enumerate(shapes):
            path = Path(self.dir) / f"m{i}.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("auswahl_manifest.json", shape)
                zf.writestr("rezepte_export/1.xml", recipe_xml("1", "Pastinaken-Suppe"))
            a = load_archive(path)                                      # must not raise
            block = lookup(a, "Pastinake")                              # and lookups on the result must not raise either
            self.assertIn(block["match_status"], ("archive_unavailable", "matches_found", "no_match_found"))
            if shape.startswith('{"rezepte": [{"datei"'):               # wrong field types are coerced, recipe still readable
                self.assertEqual(len(a.recipes), 1)
            else:
                self.assertFalse(a.available, shape)

    def test_non_utf8_manifest_is_unavailable(self):
        path = Path(self.dir) / "latin.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("auswahl_manifest.json", b'{"rezepte": []} \xff\xfe')
        self.assertFalse(load_archive(path).available)

    def test_manifest_path_traversal_is_ignored(self):
        path = make_zip(self.dir, [("1", "Pastinaken-Suppe", [], "")])
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("auswahl_manifest.json"))
        manifest["rezepte"].append({"id": "evil", "titel": "Evil", "datei": "../../etc/passwd", "hauptkategorie": "x"})
        with zipfile.ZipFile(path, "a") as zf:
            zf.writestr("auswahl_manifest.json", json.dumps(manifest))                             # duplicate name: newest wins
        a = load_archive(path)
        self.assertEqual([r.id for r in a.recipes], ["1"])
        self.assertGreaterEqual(a.skipped, 1)

    # ---- wiring
    def test_proposals_get_real_archive_blocks_and_stay_labelled(self):
        a = self.archive([("1", "Pastinaken-Suppe", [], "")])
        accepted, _ = propose_with_archive(a)(set(), 5)
        self.assertTrue(all(p["archive"]["source"] == "export" for p in accepted))
        past = next(p for p in accepted if p["topic"] == "Pastinake")
        self.assertEqual(past["archive"]["match_status"], "matches_found")
        self.assertIn("MOCK", past["trend"]["why_relevant"])               # trend evidence is still mock and says so
        self.assertIn("real local export", archive_summary(past)[1])
        un, _ = propose_with_archive(load_archive(None))(set(), 5)
        self.assertTrue(all(p["archive"]["match_status"] == "archive_unavailable" for p in un))

    def test_plain_stub_archive_is_labelled_mock(self):
        accepted, _ = Agents().propose(set(), 5)
        self.assertIn("MOCK", archive_summary(accepted[0])[1])

    def test_archive_titles_cannot_inject_markdown(self):
        block = {"source": "export", "match_status": "matches_found", "repetition_risk": "low", "available": True,
                 "similar_recipes": [{"title": "**x** [click](http://evil.example)", "category": "<b>c</b>", "why": "title contains 'x'",
                                      "publication_date": None, "publication_note": "Publication date unavailable."}]}
        text = archive_summary({"archive": block})[1]
        self.assertNotIn("[click](http://evil.example)", text)
        self.assertIn("\\[click\\]\\(http", text)

    def test_configuration_comes_from_environment_and_is_cached_per_path(self):
        path = make_zip(self.dir, [("1", "Pastinaken-Suppe", [], "")])
        arc._cache.clear()
        with mock.patch.object(arc, "_env", lambda name: str(path) if name == "EDITOR_ARCHIVE_ZIP" else ""):
            self.assertTrue(arc.configured_archive().available)
            self.assertIs(arc.configured_archive(), arc.configured_archive())
        with mock.patch.object(arc, "_env", lambda name: ""):
            self.assertFalse(arc.configured_archive().available)
        arc._cache.clear()

    def test_archive_data_never_reaches_the_audit_log(self):
        from editor.workflow import EditorWorkflow
        a = self.archive([("1", "Pastinaken-Suppe-Geheimtitel", [], "")])
        log = Path(self.dir) / "audit.jsonl"
        wf = EditorWorkflow(Agents(propose=propose_with_archive(a)), log, Path(self.dir) / "cards")
        wf.start()
        wf.select(next(p["id"] for p in wf.proposals if p["topic"] == "Pastinake"), "")
        self.assertNotIn("Geheimtitel", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
