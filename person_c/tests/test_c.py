"""Run:  python -m unittest discover -s tests -v     (no network, no keys needed)"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unittest import mock                                       # noqa: E402

from c_pipeline import images, pipeline                           # noqa: E402
from c_pipeline.archive import archive_to_flat, parse_archive_xml  # noqa: E402
from c_pipeline.config import Config                              # noqa: E402
from c_pipeline.llm import OpenAICompatClient, extract_json       # noqa: E402
from c_pipeline.nutrition_agent import compute_nutrition, load_overrides, match_ingredient  # noqa: E402
from c_pipeline.nutrition_db import NutritionDB                   # noqa: E402
from c_pipeline.recipe_agent import faithful_image_prompt         # noqa: E402
from c_pipeline.schemas import image_components_problems, image_prompt_problems, validate_recipe  # noqa: E402
from c_pipeline.render import fmt_amount, ingredient_line, render_recipe_pages, wrap_items  # noqa: E402
from c_pipeline.review_agent import code_checks                   # noqa: E402
from c_pipeline.textmetrics import wrap_text                      # noqa: E402

FIX = ROOT / "fixtures"
MOCK = json.loads((FIX / "mock_llm" / "recipe_generate.json").read_text(encoding="utf-8"))["recipes"]


def recipe(i=0, **kw):
    r = json.loads(json.dumps(MOCK[i]))
    r.update(id=f"r{i + 1}", version=1)
    r.update(kw)
    return r


class Formatting(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(fmt_amount(0.5), "½")
        self.assertEqual(fmt_amount(1.5), "1 ½")
        self.assertEqual(fmt_amount(2.5), "2 ½")
        self.assertEqual(fmt_amount(0.3), "0,3")
        self.assertEqual(fmt_amount(400), "400")
        self.assertEqual(fmt_amount("etwas"), "etwas")        # archive free text is kept as stored

    def test_ingredient_lines(self):
        self.assertEqual(ingredient_line({"name": "Butter", "quantity": 40, "unit": "g"}), "40 g Butter")
        self.assertEqual(ingredient_line({"name": "Eier", "quantity": 2, "unit": None, "note": "Größe M"}), "2 Eier (Größe M)")
        self.assertEqual(ingredient_line({"name": "Salz", "quantity": None}), "Salz")
        self.assertEqual(ingredient_line({"name": "Feta", "quantity": 100, "unit": "g", "prefix": "ca."}), "ca. 100 g Feta")
        self.assertEqual(ingredient_line({"name": "Petersilie", "quantity": 1, "unit": "Bund", "note": "zum Garnieren"}), "1 Bund Petersilie zum Garnieren")

    def test_wrap_never_drops_text(self):
        t = "Den Backofen auf 180 Grad (Umluft 160 Grad) vorheizen. Donaudampfschifffahrtsgesellschaftskapitänsmütze-Zutat."
        lines = wrap_text(t, 120, 10.2)
        self.assertEqual(re.sub(r"[\s-]", "", "".join(lines)), re.sub(r"[\s-]", "", t))

    def test_items_not_split(self):
        lines = wrap_items(["Energie: 332 kcal", "Fett: 12 g", "Kohlenhydrate: 32 g"], 90, 8.7)
        self.assertTrue(all(any(l.count(x) for x in ("kcal", " g")) for l in lines))
        self.assertEqual(sum(l.count("Fett") for l in lines), 1)


class Render(unittest.TestCase):
    def _text(self, pages):
        return re.sub(r"<[^>]+>", "\n", "".join(pages))

    def test_short_recipe_is_one_page_with_ai_label(self):
        pages = render_recipe_pages(recipe(1), None, None, None, True)
        self.assertEqual(len(pages), 1)
        txt = self._text(pages)
        self.assertIn("KI-generierter Rezeptentwurf", txt)
        self.assertIn("Seite 1 von 1", txt)

    def test_long_recipe_paginates_without_losing_content(self):
        r = recipe(0)
        r["steps"] = [{"group": None, "text": f"Schritt {n}: " + "Zwiebeln würfeln und in Butter glasig dünsten. " * 14, "uses": []} for n in range(1, 13)]
        r["ingredients"] += [{"id": f"x{n}", "group": None, "name": f"Zutat Nummer {n}", "quantity": n, "unit": "g", "note": None} for n in range(1, 25)]
        pages = render_recipe_pages(r, None, None, None, True)
        self.assertGreaterEqual(len(pages), 2)
        txt = self._text(pages)
        for n in range(1, 13):
            self.assertIn(f"Schritt {n}:", txt)
        for n in range(1, 25):
            self.assertIn(f"Zutat Nummer {n}", txt)
        for p in range(1, len(pages) + 1):
            self.assertIn(f"Seite {p} von {len(pages)}", txt)
        self.assertIn("Fortsetzung", txt)

    def test_overlong_step_is_split_not_dropped(self):
        r = recipe(1)
        sentence = "Die Masse gründlich verrühren und anschließend ruhen lassen. "
        r["steps"] = [{"group": None, "text": sentence * 90, "uses": []}]
        pages = render_recipe_pages(r, None, None, None, True)
        txt = " ".join(self._text(pages).split())          # lines of one paragraph are separate <span>s
        self.assertEqual(txt.count("Die Masse gründlich verrühren und anschließend ruhen lassen."), 90)
        self.assertGreater(len(pages), 1)

    def test_archive_recipes_render(self):
        for f in ("archive_structured.xml", "archive_attributes.xml"):
            rec = parse_archive_xml(ROOT / "tests" / "fixtures" / f)
            flat = archive_to_flat(rec)
            pages = render_recipe_pages(flat, None, None, None, False)
            self.assertGreaterEqual(len(pages), 1)
            self.assertIn("Bezugsmenge nicht angegeben" if flat["archive_nutrition"] else "Zutaten", self._text(pages))


class Review(unittest.TestCase):
    def test_clean_recipes_have_no_errors(self):
        for i in (1,):
            f = code_checks(recipe(i))
            self.assertEqual([x for v in f.values() for x in v if x["severity"] == "error"], [])

    def test_detects_planted_defects(self):
        f = code_checks(recipe(0))          # mock v1 contains: unused Lorbeerblätter, Butter 20 g vs 30 g in step
        msgs = " ".join(x["message"] for v in f.values() for x in v if x["severity"] == "error")
        self.assertIn("Lorbeerblätter", msgs)
        self.assertIn("Butter", msgs)

    def test_missing_quantity_and_el_tl(self):
        r = recipe(1)
        r["ingredients"][0]["quantity"] = None
        r["ingredients"].append({"id": "m1", "group": None, "name": "Majoran", "quantity": 2, "unit": "EL", "note": None})
        r["steps"][0]["text"] += " 1 TL Majoran zugeben."
        f = code_checks(r)
        self.assertTrue(any("ohne Mengenangabe" in x["message"] for x in f.get("quantity_completeness", [])))
        self.assertTrue(any(x["severity"] == "error" for x in f.get("tbsp_tsp", [])))

    def test_salt_and_pepper_exempt(self):
        f = code_checks(recipe(1))
        self.assertFalse(any("Salz" in x["message"] or "Pfeffer" in x["message"] for x in f.get("quantity_completeness", [])))

    def test_step_order(self):
        r = recipe(1)
        r["steps"] = [{"group": None, "text": "Quiche im Ofen backen.", "uses": []}, {"group": None, "text": "Backofen auf 180 Grad vorheizen.", "uses": []}, {"group": None, "text": "Servieren.", "uses": []}]
        self.assertTrue(any(x["severity"] == "error" for x in code_checks(r).get("step_order", [])))


class Nutrition(unittest.TestCase):
    db = NutritionDB.load(FIX / "nutrition_mini_SYNTHETIC.csv")

    def test_per_serving_and_assumptions_logged(self):
        r = recipe(1)           # only foods that exist in the synthetic fixture, so the totals are complete
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kartoffeln", "quantity": 500, "unit": "g", "note": None},
                            {"id": "b", "group": None, "name": "Zwiebeln", "quantity": 2, "unit": None, "note": None},
                            {"id": "c", "group": None, "name": "Butter", "quantity": 2, "unit": "EL", "note": None},
                            {"id": "d", "group": None, "name": "Gemüsebrühe", "quantity": 500, "unit": "ml", "note": None}]
        n = compute_nutrition(r, self.db, None)
        self.assertEqual(n["reference"], "per_serving")
        self.assertTrue(n["per_serving"]["kcal"])
        zw = next(x for x in n["ingredients"] if "Zwiebel" in x["original"])
        self.assertTrue(zw["assumption"] and zw["confidence"] < 0.7)      # piece weight is an assumption
        self.assertTrue(all("confidence" in x and "db_name" in x and "conversion" in x for x in n["ingredients"]))

    def test_unmatched_is_reported_not_invented(self):
        n = compute_nutrition(recipe(1), self.db, None)
        self.assertTrue(any("Gouda" in u["original"] for u in n["unmatched"]))
        self.assertTrue(n["coverage"]["share"] < 1.0)

    def test_fixture_is_flagged(self):
        self.assertTrue(compute_nutrition(recipe(0), self.db, None)["db"]["synthetic_fixture"])


class NutritionRealRunFixes(unittest.TestCase):
    db = NutritionDB.load(FIX / "nutrition_mini_SYNTHETIC.csv")

    def test_tiny_spice_is_negligible_not_unmatched(self):
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kartoffeln", "quantity": 500, "unit": "g", "note": None},
                            {"id": "b", "group": None, "name": "Lorbeerblätter", "quantity": 2, "unit": "Blatt", "note": None},
                            {"id": "c", "group": None, "name": "Muskat", "quantity": 1, "unit": "Msp.", "note": "gerieben"}]
        n = compute_nutrition(r, self.db, None)
        self.assertEqual(n["unmatched"], [])
        self.assertEqual({x["ingredient_id"] for x in n["negligible"]}, {"b", "c"})
        self.assertEqual(n["coverage"]["share"], 1.0)          # negligible amounts do not count against coverage

    def test_non_spice_without_match_stays_unmatched(self):
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kassler Kamm", "quantity": 400, "unit": "g", "note": None}]
        n = compute_nutrition(r, self.db, None)
        self.assertEqual(len(n["unmatched"]), 1)
        self.assertEqual(n["per_serving"]["kcal"], None)       # nothing invented

    def test_llm_search_terms_are_verified_in_code(self):
        class Fake:
            def chat_json(self, system, user, validate=None, retries=0, temperature=0.0):
                if "TASK: nutrition_terms" in user:
                    return {"terms": ["Parmesan"]}
                return {"choice": None, "confidence": 0.0, "reason": "-"}
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Reibekäse Grana", "quantity": 50, "unit": "g", "note": None}]
        n = compute_nutrition(r, self.db, Fake())
        self.assertEqual(n["ingredients"][0]["db_name"], "Parmesan")
        self.assertEqual(n["ingredients"][0]["match"], "alias")
        self.assertLess(n["ingredients"][0]["confidence"], 0.85)


class ClosestCategory(unittest.TestCase):
    db = NutritionDB.load(FIX / "nutrition_mini_SYNTHETIC.csv")

    class Fake:
        def chat_json(self, system, user, validate=None, retries=0, temperature=0.0):
            if "TASK: nutrition_category" in user:
                return {"terms": ["Lachs"]}
            if "TASK: nutrition_closest" in user:
                return {"choice": 0, "confidence": 0.9, "reason": "Test"}
            return {"choice": None, "confidence": 0.0, "reason": "-", "terms": []}

    def test_material_ingredient_gets_labelled_closest_entry(self):
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kartoffeln", "quantity": 500, "unit": "g", "note": None},
                            {"id": "b", "group": None, "name": "Kassler Kamm", "quantity": 400, "unit": "g", "note": None}]
        n = compute_nutrition(r, self.db, self.Fake())
        row = next(x for x in n["ingredients"] if x["ingredient_id"] == "b")
        self.assertEqual(row["match"], "closest_category")
        self.assertLessEqual(row["confidence"], 0.5)
        self.assertFalse(n["incomplete"])
        self.assertTrue(any("nächstliegender" in x for x in n["notes"]))
        txt = " ".join(re.sub(r"<[^>]+>", " ", "".join(render_recipe_pages(r, n, None, None, True))).split())
        self.assertIn("Nur näherungsweise zugeordnet", txt)

    def test_trivial_amount_is_not_approximated(self):
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kassler Kamm", "quantity": 20, "unit": "g", "note": None}]
        n = compute_nutrition(r, self.db, self.Fake())
        self.assertEqual(len(n["unmatched"]), 1)


class IncompleteGuard(unittest.TestCase):
    db = NutritionDB.load(FIX / "nutrition_mini_SYNTHETIC.csv")

    def test_material_gap_means_no_values_on_card(self):
        r = recipe(1)
        r["ingredients"] = [{"id": "a", "group": None, "name": "Kartoffeln", "quantity": 500, "unit": "g", "note": None},
                            {"id": "b", "group": None, "name": "Kassler Kamm", "quantity": 400, "unit": "g", "note": None}]
        n = compute_nutrition(r, self.db, None)
        self.assertTrue(n["incomplete"])
        self.assertTrue(all(v is None for v in n["per_serving"].values()))      # no partial sums presented as per serving
        self.assertEqual(n["coverage"]["quality"], "unvollständig")
        txt = " ".join(re.sub(r"<[^>]+>", " ", "".join(render_recipe_pages(r, n, None, None, True))).split())
        self.assertIn("nicht angegeben", txt)
        self.assertNotIn("Energie:", txt)

    def test_duplicate_tip_heading_is_stripped(self):
        r = recipe(1)
        r["serving_tip"] = "Unser Tipp: Mit Brot servieren."
        txt = re.sub(r"<[^>]+>", "\n", "".join(render_recipe_pages(r, None, None, None, True)))
        self.assertEqual(txt.count("Unser Tipp"), 1)


class Llm(unittest.TestCase):
    def test_gateway_url_gets_v1(self):
        c = OpenAICompatClient(Config(llm_base_url="https://example.org/access_x/ai_gateway", llm_model="m"))
        self.assertEqual(c._url(), "https://example.org/access_x/ai_gateway/v1/chat/completions")
        c = OpenAICompatClient(Config(llm_base_url="https://example.org/v1/", llm_model="m"))
        self.assertEqual(c._url(), "https://example.org/v1/chat/completions")

    def test_extract_json(self):
        self.assertEqual(extract_json('Hier:\n```json\n{"a": [1, {"b": "}"}]}\n```'), {"a": [1, {"b": "}"}]})


class EndToEnd(unittest.TestCase):
    def test_offline_demo_pipeline(self):
        os.environ["OFFLINE"] = "1"
        os.environ["NUTRITION_CSV"] = str(FIX / "nutrition_mini_SYNTHETIC.csv")
        os.environ["ARCHIVE_DIR"] = ""
        cfg = Config.from_env()
        with tempfile.TemporaryDirectory() as d:
            res = pipeline.run_stage_c(cfg, FIX / "mock_selection.json", FIX / "mock_proposals.json", Path(d))
            self.assertEqual(len(res["recipes"]), 2)
            for name in ("recipes.json", "review.json", "nutrition.json", "stage_c_log.json", "cards/r1.html", "cards/r2.html", "cards/das_schmeckt_rezepte.html"):
                self.assertTrue((Path(d) / name).exists(), name)
            rounds = json.loads((Path(d) / "review.json").read_text(encoding="utf-8"))
            r1 = [x for x in rounds if x["recipe_id"] == "r1"]
            self.assertEqual([x["overall"] for x in r1], ["revise", "pass"])       # loop: defect found, fixed, re-reviewed
            self.assertLessEqual(len(r1), 3)                                       # max 2 corrections
            html = (Path(d) / "cards" / "das_schmeckt_rezepte.html").read_text(encoding="utf-8")
            self.assertIn("KI-generierter Rezeptentwurf", html)
            self.assertTrue(all(r["ai_generated"] for r in res["recipes"]))
            # editor round
            out = pipeline.run_editor_round(cfg, "r1", "weniger deftig", Path(d), make_image=False)
            self.assertEqual(out["review"]["round_type"], "editor")



class ImageContract(unittest.TestCase):
    """The picture must be a true representation of the recipe: only visible components, no invented food."""
    ings = [{"id": "i1", "name": "Grünkohl"}, {"id": "i2", "name": "Kartoffeln"}, {"id": "i3", "name": "Kassler Kamm"},
            {"id": "i4", "name": "Zwiebeln"}, {"id": "i5", "name": "Gemüsebrühe"}, {"id": "i6", "name": "Rapsöl"},
            {"id": "i7", "name": "Salz"}, {"id": "i8", "name": "Senf"}]

    def test_components_are_ids_of_visible_ingredients(self):
        self.assertEqual(image_components_problems(["i1", "i2", "i3", "i4"], self.ings), [])
        self.assertTrue(image_components_problems([], self.ings))                       # empty is not a list of components
        self.assertTrue(image_components_problems(["i1", "i1"], self.ings))             # duplicate
        self.assertTrue(image_components_problems(["i9"], self.ings))                   # unknown id
        for invisible in ("i5", "i6", "i7", "i8"):                                      # broth, frying oil, salt, mustard
            self.assertTrue(image_components_problems(["i1", invisible], self.ings), invisible)

    def test_prompt_rejects_food_that_is_not_in_the_recipe(self):
        bad = ("A bowl of kale stew with rye bread beside it", "A bowl of kale stew with a wedge of lemon",
               "A bowl of kale stew sprinkled with chopped parsley", "A bowl of kale stew with a swirl of mustard",
               "A bowl of kale stew, garnished with herbs", "Eine Schüssel Grünkohl")
        for p in bad:
            self.assertTrue(image_prompt_problems(p, self.ings), p)

    def test_prompt_accepts_the_real_components(self):
        good = ("A deep rustic ceramic bowl of dark green kale stew with soft potato chunks, translucent onion and "
                "cubes of smoked cured pork. Bare wooden table, linen cloth, nothing beside the bowl.")
        self.assertEqual(image_prompt_problems(good, self.ings), [])
        self.assertEqual(validate_recipe({**recipe(0), "image_prompt": good, "image_components": ["i1"],
                                          "ingredients": self.ings, "steps": [{"text": "Kochen.", "uses": ["i1"]}]}), [])

    def test_faithful_image_prompt_sends_problems_back(self):
        class ValidatingFake:
            """Like OpenAICompatClient.chat_json: every canned reply is validated, a rejected one is asked again."""
            def __init__(self, replies):
                self.replies, self.rejected = list(replies), []

            def chat_json(self, system, user, *, validate=None, retries=2, temperature=0.4):
                for r in self.replies:
                    problems = validate(r) if validate else []
                    if not problems:
                        return r
                    self.rejected.append(problems)
                raise AssertionError("fake ran out of replies")

        r = {**recipe(0), "ingredients": self.ings, "steps": [{"text": "Alles kochen.", "uses": ["i1"]}]}
        client = ValidatingFake([
            {"components": ["i1", "i7"], "prompt": "A bowl of kale stew with rye bread and a swirl of mustard"},
            {"components": ["i1", "i2", "i3"], "prompt": "A deep ceramic bowl of kale stew with potato chunks and "
                                                         "cubes of smoked cured pork on a bare wooden table"},
        ])
        out = faithful_image_prompt(client, r)
        self.assertEqual(out["components"], ["i1", "i2", "i3"])
        self.assertNotIn("bread", out["prompt"])
        self.assertEqual(len(client.rejected), 1)
        self.assertTrue(any("Salz" in m for m in client.rejected[0]))        # the invisible component was named
        self.assertTrue(any("bread" in m for m in client.rejected[0]))


class VisionVerification(unittest.TestCase):
    cfg = Config(llm_base_url="https://example.org", llm_model="text-only-model", bfl_api_key="x")
    rec = {"id": "r1", "title": "Grünkohl-Eintopf", "image_prompt": "A bowl of kale stew with potato chunks",
           "image_components": ["i1", "i2"],
           "ingredients": [{"id": "i1", "name": "Grünkohl"}, {"id": "i2", "name": "Kartoffeln"}]}

    class VisionFake:
        """Returns canned verifications; models listed in `blind` raise like a model without image support."""
        def __init__(self, replies, blind=()):
            self.replies, self.blind, self.seen = list(replies), set(blind), []

        def chat_vision_json(self, system, text, image_path, *, validate=None, retries=1, temperature=0.0, model=None):
            self.seen.append(model)
            if model in self.blind:
                raise RuntimeError("this model cannot read images")
            obj = self.replies.pop(0)
            problems = validate(obj) if validate else []
            if problems:
                raise RuntimeError(f"invalid reply: {problems}")
            return obj

    @staticmethod
    def _v(score, extra=(), missing=()):
        return {"visible_foods": ["kale", "potatoes"], "matches_recipe_score": score,
                "foods_not_in_recipe": list(extra), "missing_components": list(missing)}

    @staticmethod
    def _fake_flux(n=(0,)):
        """Stand-in for generate_image: writes a numbered file so we can see which picture was kept."""
        def gen(prompt, out_path, cfg, timeout_s=150):
            n = gen.calls = gen.calls + 1
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(f"image {n}".encode())
            return {"model": cfg.bfl_model, "prompt": prompt, "path": str(out_path), "status": "generated", "note": None}
        gen.calls = 0
        return gen

    def test_fallback_vision_model_is_used_when_the_configured_one_is_blind(self):
        client = self.VisionFake([self._v(9)], blind=[None])
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "r1.jpg"
            img.write_bytes(b"x")
            res, errs = images.verify_image(client, img, self.rec, ["Grünkohl"], [None, images.VISION_FALLBACK_MODEL])
        self.assertEqual(res["model"], images.VISION_FALLBACK_MODEL)
        self.assertEqual(client.seen, [None, images.VISION_FALLBACK_MODEL])
        self.assertEqual(len(errs), 1)

    def test_good_picture_is_not_regenerated(self):
        gen = self._fake_flux()
        client = self.VisionFake([self._v(9)])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(images, "generate_image", gen):
            meta = images.generate_and_verify(self.rec, self.cfg, client, d)
            self.assertEqual((Path(d) / "img" / "r1.jpg").read_bytes(), b"image 1")
        self.assertEqual(gen.calls, 1)
        self.assertFalse(meta["verification"]["retried"])
        self.assertEqual(meta["verification"]["score"], 9)
        self.assertEqual(len(meta["verification"]["attempts"]), 1)

    def test_foreign_food_triggers_one_reinforced_retry_and_the_better_picture_is_kept(self):
        gen = self._fake_flux()
        client = self.VisionFake([self._v(5, extra=["bread"]), self._v(9)])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(images, "generate_image", gen):
            meta = images.generate_and_verify(self.rec, self.cfg, client, d)
            self.assertEqual((Path(d) / "img" / "r1.jpg").read_bytes(), b"image 2")    # the better one was kept
            self.assertFalse((Path(d) / "img" / "r1_attempt2.jpg").exists())           # no leftovers
        v = meta["verification"]
        self.assertEqual(gen.calls, 2)                                                 # exactly ONE retry
        self.assertTrue(v["retried"])
        self.assertEqual(v["kept_attempt"], 2)
        self.assertEqual(v["score"], 9)
        self.assertEqual([a["attempt"] for a in v["attempts"]], [1, 2])                # both attempts are documented
        self.assertEqual(v["attempts"][0]["foods_not_in_recipe"], ["bread"])
        self.assertIn("MUST show", v["attempts"][1]["prompt"])
        self.assertIn("MUST NOT show", v["attempts"][1]["prompt"])
        self.assertIn("bread", v["attempts"][1]["prompt"])

    def test_worse_retry_keeps_the_first_picture(self):
        gen = self._fake_flux()
        client = self.VisionFake([self._v(6), self._v(3)])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(images, "generate_image", gen):
            meta = images.generate_and_verify(self.rec, self.cfg, client, d)
            self.assertEqual((Path(d) / "img" / "r1.jpg").read_bytes(), b"image 1")
        self.assertEqual(meta["verification"]["kept_attempt"], 1)
        self.assertEqual(meta["verification"]["score"], 6)

    def test_without_a_vision_model_the_run_continues(self):
        gen = self._fake_flux()
        client = self.VisionFake([], blind=[None, images.VISION_FALLBACK_MODEL])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(images, "generate_image", gen):
            meta = images.generate_and_verify(self.rec, self.cfg, client, d)
        self.assertEqual(meta["status"], "generated")
        self.assertEqual(meta["verification"], "nicht verfügbar")
        self.assertIn("Vision-Modell", meta["verification_note"])
        self.assertEqual(gen.calls, 1)

    def test_malformed_verification_json_is_rejected(self):
        self.assertTrue(images._verification_errors({"matches_recipe_score": 42}))
        self.assertTrue(images._verification_errors({"matches_recipe_score": 8, "visible_foods": "kale"}))
        self.assertEqual(images._verification_errors(self._v(8)), [])


class IngredientOverrides(unittest.TestCase):
    """Pinned ingredient -> db_id assignments: the same recipe must give the same kcal in every run."""
    db = NutritionDB.load(FIX / "nutrition_mini_SYNTHETIC.csv")
    kassler = {"id": "i3", "name": "Kassler Kamm", "quantity": 400, "unit": "g", "note": None}

    class PickyFake:
        """An LLM that would choose a different candidate on every call."""
        def __init__(self):
            self.calls = 0

        def chat_json(self, system, user, *, validate=None, retries=0, temperature=0.0):
            self.calls += 1
            if "TASK: nutrition_category" in user:
                return {"terms": ["Lachs", "Entenbrust"]}
            if "TASK: nutrition_closest" in user:
                return {"choice": self.calls % 2, "confidence": 0.9, "reason": "Test"}
            return {"choice": None, "confidence": 0.0, "reason": "-", "terms": []}

    def test_pinned_entry_wins_over_the_llm_choice(self):
        table = {"kassler kamm": {"db_id": "90019", "confidence": 0.5,
                                  "why": "nächstliegender Eintrag (Annahme; feste Zuordnung): Test"}}
        llm = self.PickyFake()
        m = match_ingredient(self.db, self.kassler, llm, overrides=table)
        self.assertEqual(m.entry.db_id, "90019")
        self.assertEqual(m.method, "closest_category")                 # stays a labelled assumption
        self.assertLessEqual(m.confidence, 0.5)
        self.assertIn("nächstliegender Eintrag (Annahme", m.why)
        self.assertEqual(llm.calls, 0)                                 # pinned: the LLM is never asked

    def test_unknown_db_id_falls_back_to_the_normal_search(self):
        table = {"kassler kamm": {"db_id": "does-not-exist", "confidence": 0.5}}
        m = match_ingredient(self.db, self.kassler, None, overrides=table)
        self.assertIsNone(m.entry)

    def test_table_file_is_read_with_normalized_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ov.json"
            p.write_text(json.dumps({"overrides": {"Kassler Kamm": {"db_id": "90019"}}}), encoding="utf-8")
            table = load_overrides(str(p))
        self.assertIn("kassler kamm", table)
        self.assertEqual(table["kassler kamm"]["db_id"], "90019")

    def test_shipped_table_pins_kassler_reproducibly(self):
        csv = ROOT / "data" / "nutrition.csv"
        if not csv.is_file():
            self.skipTest("real nutrition CSV not present")
        db = NutritionDB.load(csv)
        r = recipe(0)
        r["ingredients"] = [{"id": "i1", "group": None, "name": "Kartoffeln", "quantity": 600, "unit": "g", "note": None},
                            {"id": "i2", "group": None, "name": "Kassler Kamm", "quantity": 400, "unit": "g", "note": None}]
        r["steps"] = [{"text": "Alles kochen.", "uses": ["i1", "i2"]}]
        runs = [compute_nutrition(r, db, self.PickyFake()) for _ in range(2)]
        self.assertEqual(runs[0]["per_serving"]["kcal"], runs[1]["per_serving"]["kcal"])
        row = next(x for x in runs[0]["ingredients"] if x["ingredient_id"] == "i2")
        self.assertEqual(row["db_id"], "1118")
        self.assertEqual(row["match"], "closest_category")
        self.assertTrue(any("nächstliegender Eintrag (Annahme)" in n for n in runs[0]["notes"]))


if __name__ == "__main__":
    unittest.main()
