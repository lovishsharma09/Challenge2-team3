#!/usr/bin/env python3
"""CLI for Person C (stages 06-09).  Examples:

  python run_c.py --models                       # list models offered by the Tesseracted gateway
  python run_c.py --ping                         # test LLM connection
  python run_c.py --demo                         # full offline demo with mock data (no keys, no network)
  python run_c.py --selection output/selection.json --proposals output/proposals.json
  python run_c.py --editor-comment r1 "weniger Sahne, alltagstauglicher"
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from c_pipeline.config import Config  # noqa: E402
from c_pipeline import pipeline  # noqa: E402
from c_pipeline.llm import OpenAICompatClient, get_client  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selection", type=Path, default=Path("output/selection.json"))
    ap.add_argument("--proposals", type=Path, default=Path("output/proposals.json"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-image", action="store_true")
    ap.add_argument("--servings", type=int, default=4)
    ap.add_argument("--demo", action="store_true", help="offline demo: mock LLM, placeholder images, synthetic nutrition fixture")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--models", action="store_true")
    ap.add_argument("--renutrition", action="store_true", help="recompute nutrition for the existing recipes, then re-render (keeps recipes and images)")
    ap.add_argument("--images-only", action="store_true", help="generate the FLUX images for the existing recipes, then re-render")
    ap.add_argument("--render-only", action="store_true", help="re-render cards from existing output/recipes.json + nutrition.json (no AI calls)")
    ap.add_argument("--check-nutrition", action="store_true", help="print what was parsed from the nutrition CSV (run this first with the real file)")
    ap.add_argument("--editor-comment", nargs=2, metavar=("RECIPE_ID", "COMMENT"))
    a = ap.parse_args()

    if a.demo:
        os.environ["OFFLINE"] = "1"
        os.environ.setdefault("NUTRITION_CSV", str(ROOT / "fixtures" / "nutrition_mini_SYNTHETIC.csv"))
        a.selection, a.proposals = ROOT / "fixtures" / "mock_selection.json", ROOT / "fixtures" / "mock_proposals.json"
        a.out = a.out or ROOT / "output_demo"
    cfg = Config.from_env()
    if a.check_nutrition:
        from collections import Counter
        from c_pipeline.nutrition_db import NutritionDB
        if not (cfg.nutrition_csv and Path(cfg.nutrition_csv).is_file()):
            print("NUTRITION_CSV is not set or the file does not exist (see .env.example)")
            return 1
        db = NutritionDB.load(cfg.nutrition_csv)
        print(f"{len(db.entries)} entries | version {db.version} | synthetic fixture: {db.is_fixture}")
        print("reference units:", dict(Counter(f"{e.basis_amount:g} {e.basis_unit}" for e in db.entries)))
        print("entries without kcal:", sum(1 for e in db.entries if e.nutrients.get("kcal") is None))
        for e in db.entries[:5]:
            print(" -", e.name, "|", e.basis_text, "|", {k: v for k, v in list(e.nutrients.items())[:4]})
        return 0
    if a.models:
        print("\n".join(OpenAICompatClient(cfg).list_models()))
        return 0
    if a.ping:
        print(get_client(cfg).ping())
        return 0
    if a.renutrition:
        res = pipeline.renutrition(cfg, a.out)
        print("\nDONE ->", res["combined"])
        return 0
    if a.images_only:
        res = pipeline.images_only(cfg, a.out)
        print("\nDONE ->", res["combined"])
        return 0
    if a.render_only:
        res = pipeline.render_only(cfg, a.out)
        print("\nDONE ->", res["combined"])
        return 0
    if a.editor_comment:
        res = pipeline.run_editor_round(cfg, a.editor_comment[0], a.editor_comment[1], a.out, not a.no_image)
        print("cards:", res["combined"])
        return 0
    res = pipeline.run_stage_c(cfg, a.selection, a.proposals, a.out, not a.no_image, a.servings)
    print("\nDONE ->", res["combined"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
