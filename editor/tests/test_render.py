import re
import tempfile
import unittest
from pathlib import Path

from editor.render import fmt_amount, ingredient_text, render_cards, render_recipe, slug, wrap


def plain(page: str) -> str:
    """Visible text of a rendered card with line breaks turned into spaces."""
    body = re.sub(r"<(script|style)>.*?</\1>", " ", page, flags=re.S)
    body = body.replace("</span>", " ").replace("</p>", " ")
    return " ".join(re.sub(r"<[^>]+>", " ", body).split()).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def recipe(n_ing=4, n_steps=3, **extra):
    r = {"title": "Kürbis aus dem Ofen", "subtitle": "klassisch", "servings": 4, "prep_time_minutes": 15,
         "cook_time_minutes": 25,
         "ingredients": [{"name": f"Zutat {i}", "amount": 100 + i if i % 2 else 1.5, "unit": "g" if i % 2 else "EL"}
                         for i in range(n_ing)] + [{"name": "Salz", "amount": None, "unit": ""}],
         "steps": [f"Schritt {i}: Zutat {i} verarbeiten und abschmecken." for i in range(n_steps)], "image_url": None}
    r.update(extra)
    return r


class RenderTest(unittest.TestCase):
    def test_content_is_copied_verbatim_and_complete(self):
        r = recipe(30, 12)
        text = plain(render_recipe(r, None, []))
        for ing in r["ingredients"]:
            self.assertIn(ingredient_text(ing), text)
        for step in r["steps"]:
            self.assertIn(step, text)

    def test_amounts_are_formatted_not_converted(self):
        self.assertEqual(fmt_amount(1.5), "1,5")
        self.assertEqual(fmt_amount(2.0), "2")
        self.assertEqual(fmt_amount(None), "")
        self.assertEqual(ingredient_text({"name": "Salz", "amount": None, "unit": ""}), "Salz")
        self.assertEqual(ingredient_text({"name": "Olivenöl", "amount": 2, "unit": "EL"}), "2 EL Olivenöl")

    def test_times_are_shown_separately_never_summed(self):
        text = plain(render_recipe(recipe(), None, []))
        self.assertIn("Vorbereitung: 15 Min.", text)
        self.assertIn("Garen: 25 Min.", text)
        self.assertNotIn("40 Min", text)

    def test_missing_optional_fields_are_omitted_not_invented(self):
        r = recipe()
        for k in ("prep_time_minutes", "cook_time_minutes", "subtitle"):
            r.pop(k)
        text = plain(render_recipe(r, None, []))
        self.assertNotIn("Vorbereitung", text)
        self.assertNotIn("Garen", text)
        self.assertNotIn("None", text)

    def test_pending_nutrition_is_omitted_and_never_zero(self):
        text = plain(render_recipe(recipe(), {"status": "pending", "per_serving": None, "assumptions": []}, []))
        self.assertNotIn("Nährwerte", text)
        self.assertNotIn("0 kcal", text)

    def test_available_nutrition_is_shown_per_serving_with_assumptions(self):
        nut = {"status": "ok", "per_serving": {"kcal": 440, "fat_g": 34, "carbs_g": None, "protein_g": 30},
               "assumptions": [{"original": "Dukkah", "used": "Haselnüsse", "confidence": "mittel"}]}
        text = plain(render_recipe(recipe(), nut, []))
        self.assertIn("Nährwerte pro Portion", text)
        self.assertIn("Energie: 440 kcal", text)
        self.assertNotIn("Kohlenhydrate", text)             # unknown value is left out, not printed as 0
        self.assertIn("Annahme: Dukkah → Haselnüsse (Sicherheit: mittel)", text)

    def test_ai_label_and_warnings_on_every_card(self):
        w = [{"message": "Titel könnte präziser sein.", "dismiss_reason": "ok so"}]
        text = plain(render_recipe(recipe(), None, w))
        self.assertIn("KI-generierter Rezeptentwurf", text)
        self.assertIn("Redaktionell freigegeben mit offenen Prüfhinweisen", text)
        self.assertIn("Titel könnte präziser sein.", text)
        self.assertNotIn("Redaktionell freigegeben", plain(render_recipe(recipe(), None, [])))

    def test_long_content_continues_on_numbered_pages_with_header_and_footer(self):
        page = render_recipe(recipe(40, 25, serving_tip="Tipp " * 30), None, [])
        n = int(re.search(r"Seite 1 von (\d+)", page).group(1))
        self.assertGreaterEqual(n, 2)
        for i in range(1, n + 1):
            self.assertIn(f"Seite {i} von {n}", page)
        self.assertGreaterEqual(page.count("(Fortsetzung)"), n - 1)
        self.assertGreaterEqual(page.count('class="page-footer"'), n)
        self.assertEqual(page.count("<header class=\"page-header\">"), n)

    def test_one_very_long_step_is_split_across_pages_without_losing_words(self):
        words = [f"wort{i}" for i in range(900)]
        r = recipe(3, 0, steps=[" ".join(words)])
        text = plain(render_recipe(r, None, []))
        self.assertTrue(all(w in text.split() for w in words))
        self.assertIn("Seite 2 von", text)

    def test_overlong_word_is_hard_split_not_dropped(self):
        lines = wrap("Donaudampfschifffahrtsgesellschaftskapitänsmützenabzeichen", 60, 10)
        self.assertEqual("".join(lines), "Donaudampfschifffahrtsgesellschaftskapitänsmützenabzeichen")
        self.assertGreater(len(lines), 1)

    def test_html_is_escaped(self):
        r = recipe(title='<script>alert(1)</script> & "Co"', steps=["<img src=x onerror=1> bleibt Text"])
        page = render_recipe(r, None, [])
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_image_handling(self):
        self.assertIn("Noch kein Bild", render_recipe(recipe(), None, []))
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "x.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            page = render_recipe(recipe(image_path=str(img)), None, [])
        self.assertIn("data:image/png;base64,", page)
        self.assertIn("KI-generiertes Bild", page)
        self.assertNotIn("file://", render_recipe(recipe(image_url="file:///etc/passwd"), None, []))

    def test_uses_template_assets_and_writes_two_files(self):
        with tempfile.TemporaryDirectory() as d:
            files = render_cards([recipe(), recipe(title="Zweites Rezept")], [None, None], [], "Kürbis", Path(d))
            self.assertEqual([f.name for f in files], ["kurbis-1.html", "kurbis-2.html"])
            page = files[0].read_text(encoding="utf-8")
        self.assertIn('content="A4-v5"', page)
        self.assertIn("data:image/", page)                  # logo embedded from the template header
        self.assertEqual(slug("Grünkohl & Co"), "grunkohl-co")


if __name__ == "__main__":
    unittest.main()
