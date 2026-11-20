from __future__ import annotations

import html
from pathlib import Path


class HtmlRenderer:
    def render(self, recipe_bundle: dict, nutrition_bundle: dict, output_path: Path) -> Path:
        cards = []
        nutrition_by_recipe = nutrition_bundle
        for recipe in recipe_bundle["recipes"]:
            ingredient_rows = "".join(
                "<li>"
                f"{html.escape(str(item['amount']))} "
                f"{html.escape(str(item['unit']))} "
                f"{html.escape(item['name'])}"
                "</li>"
                for item in recipe["ingredients"]
            )
            step_rows = "".join(
                f"<li>{html.escape(step)}</li>"
                for i, step in enumerate(recipe["steps"], start=1)
                if i
            )
            nutrition = nutrition_by_recipe.get("per_serving", {})
            cards.append(
                f"""
                <article class="recipe">
                  <div class="ai-label">AI-Draft</div>
                  <h1>{html.escape(recipe["title"])}</h1>
                  <p class="subtitle">{html.escape(recipe["subtitle"])}</p>
                  <div class="meta">
                    <span>{recipe["servings"]} Portionen</span>
                    <span>{recipe["prep_time_minutes"] + recipe["cook_time_minutes"]} Minuten gesamt</span>
                    <span>{html.escape(recipe["difficulty"])}</span>
                  </div>
                  <div class="columns">
                    <section><h2>Zutaten</h2><ul>{ingredient_rows}</ul></section>
                    <section><h2>Zubereitung</h2><ol>{step_rows}</ol></section>
                  </div>
                  <aside class="nutrition">
                    <strong>Nährwerte pro Portion</strong>
                    <span>{nutrition.get("kcal", 0)} kcal</span>
                    <span>{nutrition.get("fat_g", 0)} g Fett</span>
                    <span>{nutrition.get("carbs_g", 0)} g Kohlenhydrate</span>
                    <span>{nutrition.get("protein_g", 0)} g Protein</span>
                  </aside>
                </article>
                """
            )

        document = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>das schmeckt! · AI-Drafts</title>
<style>
@page {{ size: A4 portrait; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #183e30; font-family: Arial, sans-serif; }}
.recipe {{ position: relative; min-height: 273mm; padding: 12mm; border: 1px solid #006642; page-break-after: always; }}
.recipe:last-child {{ page-break-after: auto; }}
.ai-label {{ position: absolute; right: 12mm; top: 12mm; background: #fff04b; padding: 5mm 7mm; font-weight: bold; }}
h1 {{ max-width: 150mm; margin: 0 0 4mm; font-size: 28pt; }}
.subtitle {{ margin: 0 0 8mm; color: #526057; }}
.meta {{ display: flex; gap: 5mm; margin-bottom: 10mm; }}
.meta span {{ background: #edf2e9; padding: 3mm; }}
.columns {{ display: grid; grid-template-columns: 38% 62%; gap: 8mm; }}
ul, ol {{ line-height: 1.55; padding-left: 6mm; }}
.nutrition {{ position: absolute; left: 12mm; right: 12mm; bottom: 12mm; display: flex; gap: 6mm; border-top: 1px solid #006642; padding-top: 5mm; }}
@media print {{ .recipe {{ border: 0; }} }}
</style>
</head>
<body>{''.join(cards)}</body>
</html>
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(document, encoding="utf-8")
        return output_path
