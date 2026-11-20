# Person C – stages 06-09 (Recipe → Review loop → Nutrition → HTML cards)

Turns the editor-selected proposal into **two differentiated recipes**, runs the **review/correction loop**
(max 2 corrections), generates **FLUX images**, calculates **nutrition per serving** from the Swiss database and renders
**A4 recipe cards** in the "das schmeckt!" layout (with the AI-draft label). Plain Python, only `requests` required.

## 1. Quick start (2 minutes, no keys)
```bash
pip install requests
python run_c.py --demo                       # full offline run with mock data -> output_demo/cards/das_schmeckt_rezepte.html
python -m unittest discover -s tests -v      # 19 tests, no network
```
Open the HTML in Chrome. "Drucken / PDF" prints A4 at 100 % (or `python tools/export_pdf.py <html>`).
The demo contains a planted defect so you can SEE the loop: review finds it → Recipe Agent fixes it → review passes.
Demo nutrition uses a **synthetic fixture** (marked "TESTDATEN" on the card) – never present those numbers.

## 2. Real run
1. `cp .env.example .env` and fill in: Tesseracted base URL (without `/v1`) + key + a model name, BFL key. Never commit `.env`.
2. `python run_c.py --models` (lists the gateway models) and `python run_c.py --ping` (LLM works?).
3. `python run_c.py --check-nutrition` with the REAL CSV: shows entries, reference units (g vs ml) and sample rows.
   **Do this first** – the code was built against the documented header format but tested only on a synthetic fixture.
4. Put the repo data where `.env` points (nutrition CSV, template HTML, unzipped `rezepte_export` for the archive check).
5. `python run_c.py --selection output/selection.json --proposals output/proposals.json`
6. Editor sends a recipe back: `python run_c.py --editor-comment r1 "weniger Sahne, alltagstauglicher"`

## 3. Hand-off (see CONTRACTS.md)
| From → To | Files / calls |
|---|---|
| Person B → C | `selection.json` (selected id + `steering_notes`) and `proposals.json`; or call `pipeline.run_stage_c(cfg, sel, props)` |
| Person A → C (optional) | `BRAND_RULES_JSON` = distilled MarkenCI rules (default: `assets/brand_rules.default.json`, built from the PDF) |
| C → Person B | `recipes.json`, `review.json` (all rounds: issues, corrections, `archive_matches`), `nutrition.json`, `cards/*.html`, `stage_c_log.json` (decisions/assumptions/timings) |
| Editor round | `pipeline.run_editor_round(cfg, "r1", "comment")` → revise, re-review, re-nutrition, re-render (max 2 per recipe) |

## 4. What each part does
- `recipe_agent.py` – 2 recipes as JSON (German text; infinitive step style from the archive; ≤ ~14 ingredient lines; brand rules + steering notes + similar archive titles in the prompt). Output validated, up to 3 retries.
- `review_agent.py` – **code checks** for all 8 criteria (missing quantities, unused ingredients, step amounts vs list incl. split amounts, EL/TL, step order, plausibility) + completeness, brand, similarity to sibling/archive; **LLM** for culinary logic, brand fit, food safety. A different model can act as reviewer (`REVIEW_MODEL`).
- `nutrition_agent.py` + `conversions.py` – match ingredient → database entry (code first, LLM only to choose among retrieved candidates), unit → g/ml (documented assumptions with confidence), per serving. Nothing is invented: unmatched ingredients are listed, a nutrient is `null` if >5 % of the mass lacks a value.
- `images.py` – FLUX (`flux-2-pro`, polling), never blocks the workflow (placeholder + note).
- `render.py` – the template's design, rebuilt with **real pagination** (1 page if possible, follow-up pages with header/recipe reference/footer/"Seite X von Y", steps kept together, over-long steps split at sentences). Renders **archive recipes too** (`archive.archive_to_flat`). Nutrition moves into the right column when that saves a page.
- `archive.py` – reads the 5,000 SharePoint XML recipes (2 s), similarity index for the differentiation check.

## 5. Decisions and assumptions to know (also say them in the demo – it is the "consultant" part)
1. **Fidelity rule:** the renderer never invents, converts or shortens; amounts only get typographic formatting (0.5 → ½, 1.5 l → 1 ½ l, as in the magazine).
2. **AI label** on every card: yellow badge, footer text and image caption. Nutrition label says "Pro Portion, berechnet … Näherungswerte" with coverage and quality; archive recipes say "Bezugsmenge nicht angegeben" (template rule).
3. **Intro text** sits under the title (the template has no slot for it but the briefing requires an introduction).
4. **Piece/spoon weights** (e.g. 1 Zwiebel = 80 g, 1 EL Butter = 15 g) are labelled assumptions with lower confidence; tune in `assets/conversion_assumptions.json`.
5. **Not verified here (no network in my sandbox):** live Tesseracted calls (model names unknown until `--models`), live FLUX calls, the real nutrition CSV, the real template logo (falls back to a text wordmark if the HTML is not found).
6. The template's tagline alignment and exact line height of steps were inferred from its CSS (right-aligned tagline, 14.2 pt steps).

## 6. Suggested demo story (5 minutes)
Trend evidence → editor picks 1 of 5 (+ steering note) → 2 recipes → show `review.json` round 1 (real defects found) → corrected round 2 → nutrition match log with confidences → cards. Impact numbers come from `stage_c_log.json` (time per stage, issues caught, match rate) – measured, not estimated.
