# CONTRACTS.md — JSON between stages (all files in /output)

Change only after agreement in chat. `null` is allowed only where marked.

## trends.json  (stage 01 -> 02)
```json
[{
  "id": "t_gruenkohl",
  "term": "grünkohl rezept klassisch",
  "google": {"source_file": "...rising-searches_queries...csv", "row": 7,
             "kind": "rising_query", "interest": 0, "increase_pct": 650, "low_base": true},
  "wiki": {"article": "Grünkohl", "prev_7d": 2927, "latest_7d": 3322, "change_pct": 13,
           "review_required": false, "source_row": 42},
  "agreement": "both_up | google_only | wiki_only | conflict",
  "evidence_note": "one sentence, factual"
}]
```

## brand_fit.json  (stage 02 -> 03)
```json
[{"trend_id": "t_gruenkohl",
  "scores": {"seasonal_regional": 5, "accessible": 4, "everyday_practical": 4,
             "enjoyable": 4, "interesting_for_experienced_cooks": 3},
  "fit": "yes | maybe | no", "reason": "..."}]
```

## archive_check.json  (stage 03 -> 04)
```json
[{"trend_id": "t_gruenkohl",
  "similar_recipes": [{"title": "...", "id": "...", "published": "YYYY-MM-DD"}],
  "recurring_ingredients": ["..."], "recurring_methods": ["..."],
  "last_comparable_publication": "YYYY-MM-DD | null",
  "gap": "what is missing in the archive",
  "data_basis": "recipe_export | topic_map_only"}]
```
If only the topic map is available, set `data_basis` to `topic_map_only` and say so on the card.

## proposals.json  (stage 04 -> 05)
```json
{"recommended": [{      // exactly 5
   "id": "p1", "title": "...", "trend_ids": ["t_gruenkohl"],
   "why_now": "...", "brand_fit_summary": "...",
   "archive_findings": "...", "repetition_risk": "low|medium|high",
   "content_gap": "...", "recipe_ideas": ["idea A", "idea B"],
   "risks": ["..."], "validate_next": ["..."], "confidence": "high|medium|low"}],
 "rejected": [{"topic": "Kürbissuppe", "reason": "Google -30%, Wikipedia -11%"}]}
```

## selection.json  (stage 05 -> 06)
```json
{"picks": 1, "selected_ids": ["p1"], "selected_by": "name", "timestamp": "ISO-8601",
 "steering_notes": ["less dairy", "weeknight-friendly"]}   // injected into the Recipe Agent prompt
```

## recipes.json  (stage 06 -> 07, revised in loop)  — FLAT schema, as implemented by Person C
```json
[{
  "id": "r1", "proposal_id": "p1", "variant": "A", "version": 2, "ai_generated": true,
  "title": "...", "intro": "2-3 sentences",
  "servings": {"amount": 4, "unit": "Portionen"},
  "times": {"prep_min": 20, "cook_min": 35, "rest_min": null},
  "ingredients": [{"id": "i1", "group": null, "name": "Grünkohl", "quantity": 500, "unit": "g", "note": "geputzt"}],
  "steps": [{"group": null, "text": "...", "uses": ["i1"], "temperature_c": null, "duration_min": 25}],
  "serving_tip": "...", "differentiation": "one sentence vs. the sibling recipe",
  "image_components": ["i1", "i2"],          // ingredient ids VISIBLE in the finished dish (no broth/salt/spices/frying fat)
  "image_prompt": "English, finished dish only: vessel + the components above with their real cut and cooking state",
  "image_alt": "German alt text",
  "image": {"path": "output/img/r1.jpg", "status": "generated|placeholder", "model": "flux-2-pro", "prompt": "...", "note": null,
            "verification": "nicht verfügbar" | {"status": "geprüft", "model": "...", "score": 0-10, "min_score": 7,
              "foods_not_in_recipe": [], "missing_components": [], "retried": false, "kept_attempt": 1,
              "attempts": [{"attempt": 1, "prompt": "...", "score": 9, "visible_foods": ["..."], "foods_not_in_recipe": [], "missing_components": []}]}},
  "review_status": "pass|revise", "history": [{"version": 2, "reason": "...", "changes": [{"criterion": "...", "change": "..."}]}]
}]
```
`image_prompt` must name no food that is not in `ingredients` and no garnish/side dish/sauce swirl (checked in code by
`schemas.image_prompt_problems`). After every FLUX image a vision model scores the picture against `image_components`;
below 7 points or with foreign food on it the picture is regenerated ONCE with MUST/MUST-NOT lists and the better one kept.

Units allowed: g, kg, ml, l, cl, EL, TL, Prise, Msp., Stück, Bund, Stiel, Zweig, Zehe, Scheibe, Dose, Pck., Blatt, Kopf, Handvoll, Glas, Becher.
`quantity: null` only for salt and pepper. Countable items: `unit: null`, plural noun in `name`.
Archive recipes are converted into the same shape by `archive.archive_to_flat()` (so the renderer shows both).

## review.json  (stage 07: list of rounds, all recipes, all iterations)
Auto rounds: max 2 corrections. Editor-triggered rounds (`round_type: editor`, with `editor_comment`) are logged
separately, capped at 2 per recipe. 8 fixed criteria keys: `title`, `subheadings`, `quantity_plausibility`,
`quantity_completeness`, `all_ingredients_used`, `units_consistent`, `tbsp_tsp`, `step_order`.
Extras: `brand_fit`, `differentiation`, `culinary_plausibility`, `food_safety`, `completeness`.
```json
{"recipe_id": "r1", "iteration": 1, "round_type": "auto | editor", "editor_comment": null, "recipe_version": 1,
 "criteria": {"title": {"pass": true, "issues": [], "fix": null}},
 "extras": {"brand_fit": {"pass": true, "issues": [], "fix": null}},
 "overall": "pass | revise", "correction_report": "numbered, specific corrections",
 "code_findings": {"units_consistent": [{"severity": "error|warning", "message": "...", "where": "Butter"}]},
 "archive_matches": [{"id": "...", "title": "...", "modified": "YYYY-MM-DD", "similarity": 0.27}],
 "llm_used": true}
```
`issues` mixes code errors, `[LLM]` findings and `Hinweis:` warnings (warnings never fail a criterion).
`archive_matches` is exactly what Person B's editor view can show as "similar archive recipes with dates".

## nutrition.json  (stage 08 -> 09; list, one object per recipe)
```json
{"recipe_id": "r1", "reference": "per_serving", "servings": 4,
 "ingredients": [{"original": "500 g Grünkohl", "ingredient_id": "i1", "db_id": "...", "db_name": "...", "db_basis": "...",
   "grams": 500.0, "conversion": "direkte Grammangabe", "assumption": false, "match": "exact|closest|llm",
   "match_reason": "...", "confidence": 0.92, "kcal": 0.0}],
 "unmatched": [{"original": "80 g Gouda", "ingredient_id": "i8", "reason": "..."}],
 "per_serving": {"kcal": 332, "kj": 1392, "fat_g": 12, "sat_fat_g": 4.3, "carbs_g": 32, "sugar_g": 6.6, "fiber_g": 13, "protein_g": 21, "salt_g": 2.5},
 "coverage": {"ingredients_calculated": 10, "ingredients_needing_calc": 10, "share": 1.0, "mean_confidence": 0.8, "quality": "hoch|mittel|niedrig"},
 "notes": ["Salz/Pfeffer ohne Menge nicht eingerechnet"], "db": {"source": "...", "version": "7.1", "synthetic_fixture": false}}
```
A nutrient is `null` (never guessed) when more than 5 % of the matched mass lacks a database value.
Ingredients the search cannot resolve are pinned in `assets/ingredient_overrides.json` (normalized name -> `db_id`), read
before any LLM matching so repeated runs give identical values; they stay labelled `match: "closest_category"`
("nächstliegender Eintrag (Annahme)") in `notes` and on the card.

## Output  (stage 09)
`/output/cards/{recipe_id}.html` — template filled from recipes.json + nutrition.json
+ image. Must work for any recipe (variable ingredient/step count), print on A4.
