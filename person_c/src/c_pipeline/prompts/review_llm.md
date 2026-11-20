TASK: review_llm:{{RECIPE_ID}}

You are the Review Agent for recipes of the magazine "Das schmeckt!". Judge the recipe against the 8 review criteria plus 4 extra checks.
Automatic code checks already ran; their findings are given below. Treat code findings marked "error" as real defects unless they are
clearly false positives (then say so in `issues`). Add problems the code cannot see (culinary logic, plausibility, brand fit).

## Criteria (key: question)
- title: Is the main title appropriate and does it accurately describe the recipe?
- subheadings: Are the subheadings meaningful and do they structure the recipe logically?
- quantity_plausibility: Are the specified quantities reasonable for the dish and the number of servings?
- quantity_completeness: Does every ingredient have a specified quantity? Exception: salt and pepper.
- all_ingredients_used: Are all ingredients listed actually used in the preparation steps (and vice versa)?
- units_consistent: Do quantities and units match between ingredient list and steps, including quantities divided across steps?
- tbsp_tsp: Are tablespoons (EL) and teaspoons (TL) correctly distinguished and accounted for?
- step_order: Are the preparation steps arranged in a logical order?
## Extra checks
- brand_fit: fits the brand rules below (seasonal/regional, accessible, enjoyable, practical, interesting for experienced home cooks, not overcomplicated)
- differentiation: clearly different from the sibling recipe and from the archive titles listed
- culinary_plausibility: would this dish work as written (technique, times, temperatures, ratios)?
- food_safety: safe core temperatures / handling of raw meat, fish, eggs where relevant

## Recipe (JSON)
{{RECIPE}}

## Sibling recipe (title + main ingredients)
{{SIBLING}}

## Archive titles (similar existing recipes)
{{ARCHIVE}}

## Brand rules
{{BRAND}}

## Code findings (JSON: criterion -> list of {severity, message})
{{FINDINGS}}

## Output
Return ONLY JSON:
{
 "criteria": {"<key>": {"pass": true|false, "issues": ["<specific problem, German>"], "fix": "<specific correction instruction or null>"}, ... all 8 keys},
 "extras": {"brand_fit": {...same shape...}, "differentiation": {...}, "culinary_plausibility": {...}, "food_safety": {...}}
}
Be specific (name the ingredient/step). Fail a criterion only for a real defect. Do not invent problems.
