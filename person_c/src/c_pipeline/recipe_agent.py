"""Stage 06 – Recipe Agent: two clearly differentiated recipes for the selected proposal (+ revisions)."""
from __future__ import annotations
import json
from pathlib import Path

from .config import Config, ROOT
from .schemas import image_components_problems, image_prompt_problems, validate_recipe

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM = ("You are a meticulous recipe developer and editor for the German food magazine 'das schmeckt!'. "
          "You write cookable, internally consistent recipes. You answer with a single JSON object and nothing else.")
IMAGE_SYSTEM = ("You write photo briefs for a German cooking magazine. You describe ONLY what is really on the plate "
                "after this recipe has been cooked – never food that is not in the recipe. "
                "You answer with a single JSON object and nothing else.")


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def load_brand_rules(cfg: Config) -> dict:
    p = cfg.brand_rules_json if cfg.brand_rules_json and Path(cfg.brand_rules_json).is_file() else ROOT / "assets" / "brand_rules.default.json"
    return json.loads(Path(p).read_text(encoding="utf-8"))


def brand_text(rules: dict) -> str:
    """Compact text for prompts; works for the default file and for a distilled set from Person A."""
    if "must" not in rules and "rules" in rules:                  # tolerate a differently shaped file from Person A
        return json.dumps(rules, ensure_ascii=False, indent=1)[:3500]
    lines = [f"Claim: {rules.get('claim', '')}", f"Audience: {rules.get('audience', '')}"]
    for key, label in (("interest_high", "High interest"), ("interest_medium", "Medium interest"), ("no_interest", "No interest"),
                       ("expectations", "Expectations"), ("must", "Must"), ("avoid", "Avoid")):
        if rules.get(key):
            lines.append(f"{label}: " + "; ".join(rules[key]))
    if rules.get("structure"):
        lines.append("Structure: " + "; ".join(f"{k}: {v}" for k, v in rules["structure"].items()))
    return "\n".join(lines)


def _validate_generation(obj) -> list[str]:
    if not isinstance(obj, dict) or not isinstance(obj.get("recipes"), list) or len(obj["recipes"]) != 2:
        return ["root must be {\"recipes\": [R1, R2]} with exactly 2 recipes"]
    errs = []
    for n, r in enumerate(obj["recipes"], 1):
        errs += [f"recipe {n}: {e}" for e in validate_recipe(r)]
    return errs


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return x


def normalize_recipe(raw: dict, rid: str, proposal_id: str | None, variant: str, version: int = 1) -> dict:
    """Clean types/defaults; keep exactly what the model wrote otherwise (no silent content changes)."""
    r = json.loads(json.dumps(raw))
    r.pop("change_log", None) if version == 1 else None
    r["id"], r["proposal_id"], r["variant"], r["version"], r["ai_generated"] = rid, proposal_id, variant, version, True
    r["title"] = r["title"].strip()
    r["servings"] = {"amount": _num(r["servings"]["amount"]), "unit": r["servings"].get("unit") or "Portionen"}
    r["times"] = {k: _num((r.get("times") or {}).get(k)) for k in ("prep_min", "cook_min", "rest_min")}
    for ing in r["ingredients"]:
        ing["quantity"] = _num(ing.get("quantity"))
        ing.setdefault("group", None); ing.setdefault("note", None); ing.setdefault("unit", None)
    for st in r["steps"]:
        st["text"] = " ".join(st["text"].split())
        st.setdefault("group", None); st.setdefault("uses", []); st["temperature_c"] = _num(st.get("temperature_c")); st["duration_min"] = _num(st.get("duration_min"))
    r.setdefault("image_alt", r["title"])
    return r


def compact_proposal(proposal: dict, max_similar: int = 8) -> dict:
    """The proposal as the recipe writer needs it: Person A's real handoff carries trend point series, Wikimedia
    series, rank components and up to dozens of archive matches (60+ KB for one pitch) – evidence for the editor,
    noise for the prompt. Keeps every text field, drops the numeric series, caps the archive list."""
    p = {k: v for k, v in proposal.items() if k not in ("rank_components", "rank_method")}
    if isinstance(p.get("trend"), dict):
        p["trend"] = {k: v for k, v in p["trend"].items() if k not in ("points", "sparkline")}
        if isinstance(p["trend"].get("wikimedia"), dict):
            p["trend"]["wikimedia"] = {k: v for k, v in p["trend"]["wikimedia"].items() if k != "points"}
    if isinstance(p.get("archive"), dict) and isinstance(p["archive"].get("similar_recipes"), list):
        sim = p["archive"]["similar_recipes"]
        p["archive"] = {**p["archive"], "similar_recipes": sim[:max_similar],
                        **({"similar_recipes_total": len(sim)} if len(sim) > max_similar else {})}
    return p


def generate_recipes(client, proposal: dict, steering: list[str], brand_rules: dict, archive_titles: list[str],
                     servings: int = 4) -> list[dict]:
    prompt = fill(load_prompt("recipe_generate.md"),
                  PROPOSAL=json.dumps(compact_proposal(proposal), ensure_ascii=False, indent=1),
                  STEERING="\n".join(f"- {s}" for s in steering) or "(none)",
                  BRAND=brand_text(brand_rules),
                  ARCHIVE="\n".join(f"- {t}" for t in archive_titles) or "(archive not available)",
                  SERVINGS=servings)
    obj = client.chat_json(SYSTEM, prompt, validate=_validate_generation, retries=3, temperature=0.6)
    pid = proposal.get("id")
    return [normalize_recipe(r, f"r{i}", pid, "AB"[i - 1]) for i, r in enumerate(obj["recipes"], 1)]


def revise_recipe(client, recipe: dict, report: str, editor_comment: str | None, steering: list[str]) -> tuple[dict, list[dict]]:
    keep = {k: recipe[k] for k in ("title", "intro", "servings", "times", "ingredients", "steps", "serving_tip",
                                   "image_components", "image_prompt", "image_alt") if k in recipe}
    prompt = fill(load_prompt("recipe_revise.md"), RECIPE_ID=recipe["id"],
                  RECIPE=json.dumps(keep, ensure_ascii=False, indent=1), REPORT=report or "(none)",
                  EDITOR=editor_comment or "(none)", STEERING="\n".join(f"- {s}" for s in steering) or "(none)")
    obj = client.chat_json(SYSTEM, prompt, validate=validate_recipe, retries=3, temperature=0.3)
    change_log = obj.pop("change_log", []) if isinstance(obj, dict) else []
    new = normalize_recipe(obj, recipe["id"], recipe.get("proposal_id"), recipe.get("variant", "A"), recipe.get("version", 1) + 1)
    for k in ("differentiation",):
        if k in recipe and k not in new:
            new[k] = recipe[k]
    return new, change_log


def _image_brief(recipe: dict) -> str:
    """Only what the picture depends on: the dish, its parts and how the steps cut, cook and plate them."""
    return json.dumps({
        "title": recipe["title"],
        "servings": recipe.get("servings"),
        "ingredients": [{k: i.get(k) for k in ("id", "name", "quantity", "unit", "note")} for i in recipe["ingredients"]],
        "steps": [{"text": s["text"], "uses": s.get("uses", [])} for s in recipe["steps"]],
    }, ensure_ascii=False, indent=1)


def faithful_image_prompt(client, recipe: dict) -> dict:
    """Ask which ingredients are VISIBLE in the finished dish and for an English prompt that shows only those.

    Returns {"components": [ingredient ids], "prompt": str}. The reply is validated in code (ids exist, no
    seasoning/broth/frying fat, no food that the recipe does not contain) and rejected replies are sent back.
    """
    ings = recipe["ingredients"]

    def _validate(o) -> list[str]:
        if not isinstance(o, dict) or not isinstance(o.get("prompt"), str) or not o["prompt"].strip():
            return ['need {"components": ["i1", ...], "prompt": "..."}']
        return image_components_problems(o.get("components"), ings) + image_prompt_problems(o["prompt"], ings)

    user = (f"TASK: image_prompt:{recipe.get('id', 'r')}\n"
            f"Recipe (JSON):\n{_image_brief(recipe)}\n\n"
            'Return JSON {"components": ["i1", ...], "prompt": "..."}.\n'
            "components: the ids of the ingredients you can actually SEE in the finished dish. Leave out broth, water, "
            "salt, pepper, sugar, spices, bay leaves, mustard, flour and anything else that is dissolved or stirred in, "
            "and any fat that is only used for frying.\n"
            "prompt: English, 2-3 sentences, describing ONLY the finished dish: the vessel it is served in (take it from "
            "the last steps), every component from `components` with the cut and the cooking state the steps give it "
            "(diced, sliced in rings, cut in strips, fried golden, boiled soft, braised), and the plating of the last "
            "steps. Name the components, do not list ingredients.\n"
            "Forbidden in the prompt: any food that is not in the ingredient list, garnish, herbs, lemon, bread, side "
            "dishes, sauce swirls, sprinkles. Props may only be neutral (wooden surface, linen cloth) and never food. "
            "No camera, lens or lighting words (they are added later), no text, no logos, no people.")
    res = client.chat_json(IMAGE_SYSTEM, user, validate=_validate, retries=3, temperature=0.2)
    return {"components": list(res["components"]), "prompt": " ".join(res["prompt"].split())}
