TASK: recipe_revise:{{RECIPE_ID}}

You are the Recipe Agent. A Review Agent (or the editor) found problems in the recipe below. Revise it.

## Current recipe (JSON)
{{RECIPE}}

## Correction report (fix every item)
{{REPORT}}

## Editor comment (if any; highest priority)
{{EDITOR}}

## Steering notes still in force
{{STEERING}}

## Rules
- Change only what is needed to fix the listed problems; keep title, character and structure of the dish.
- Keep all hard rules of the original task: exact quantities and standard units, every ingredient used in the steps and every step
  ingredient listed, split amounts add up, correct EL/TL, logical order, German text, no unverifiable claims.
- Keep ingredient ids stable; add new ids for new ingredients.
- If the image would change (different visible ingredients), update `image_components`, `image_prompt` and `image_alt`.
- `image_components`: the ids of the ingredients you can SEE in the finished dish – never broth, water, salt, pepper, spices,
  bay leaves, mustard, anything dissolved or stirred in, or fat used only for frying.
- `image_prompt` (English, 2-3 sentences): ONLY the finished dish – the vessel, every component of `image_components` with the
  cut and cooking state from the steps, and the plating of the last steps. No food that is not in the ingredient list, and no
  garnish, side dish, bread, herbs, lemon, sauce swirl or sprinkles. Props only neutral (wood, linen), never food. No camera or
  lighting words, no text, no people.

Return ONLY JSON with the full revised recipe in the same format as before (including `image_components`) plus
"change_log": [{"criterion": "<criterion key or 'editor'>", "change": "<what you changed, German, one sentence>"}].
