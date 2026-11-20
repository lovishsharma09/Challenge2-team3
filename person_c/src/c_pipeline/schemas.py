"""Lightweight validation for the stage contracts (see CONTRACTS.md). No third-party deps."""
from __future__ import annotations
import re
from typing import Any

STANDARD_UNITS = {
    "g", "kg", "ml", "l", "cl", "EL", "TL", "Prise", "Msp.", "Stück", "Bund", "Stiel", "Zweig",
    "Zehe", "Scheibe", "Dose", "Pck.", "Blatt", "Kopf", "Handvoll", "Glas", "Becher",
}
CRITERIA = ["title", "subheadings", "quantity_plausibility", "quantity_completeness",
            "all_ingredients_used", "units_consistent", "tbsp_tsp", "step_order"]
EXTRA_CRITERIA = ["brand_fit", "differentiation", "culinary_plausibility", "food_safety", "completeness"]
SALT_PEPPER_RE = re.compile(r"^\s*(salz|pfeffer|meersalz|steinsalz|jodsalz|schwarzer pfeffer|weißer pfeffer)\b", re.I)

# --- image prompt guard: the picture must show the cooked dish and nothing else -------------------
# Ingredients that are never visible in the finished dish (dissolved, stirred in, or only used for frying).
# Compounds count ('Gemüsebrühe', 'Weizenmehl'), but a visible food that merely contains the word does not
# ('mehligkochende Kartoffeln', 'Essiggurken', 'Zuckerschoten', 'Salzkartoffeln').
INVISIBLE_INGREDIENT_RE = re.compile(
    r"salz(?!kartoffel)|pfeffer(?!minz)|brühe|bruehe|bouillon|fond\b|wasser(?!melon)|lorbeer|muskat|gewürz|gewuerz|"
    r"essig(?!gurk)|senf|zucker(?!schote|mais|erbse|melone)|mehl(?!ig)|stärke|staerke|backpulver|hefe|schmalz|"
    r"bratfett|öl\b|oel\b", re.I)
# Food an image model likes to invent -> English word in the prompt: German words that would make it real.
EXTRA_FOOD_VOCAB: dict[str, tuple[str, ...]] = {
    "lemon": ("zitrone",), "lime": ("limette",), "orange": ("orange",), "apple": ("apfel", "äpfel"),
    "pomegranate": ("granatapfel",), "parsley": ("petersilie",), "cilantro": ("koriander",),
    "coriander": ("koriander",), "dill": ("dill",), "chive": ("schnittlauch",), "basil": ("basilikum",),
    "thyme": ("thymian",), "rosemary": ("rosmarin",), "sage": ("salbei",), "mint": ("minze",),
    "herb": ("kräuter", "petersilie", "schnittlauch", "dill", "basilikum", "thymian", "rosmarin", "salbei",
             "majoran", "oregano", "kerbel"),
    "microgreen": (), "sprout": ("sprossen",), "seed": ("kerne", "samen", "saat"),
    "nut": ("nuss", "nüsse", "mandel", "kerne"), "walnut": ("walnuss",), "almond": ("mandel",),
    "bread": ("brot", "brötchen", "baguette", "toast", "semmel"), "baguette": ("baguette",),
    "toast": ("toast",), "crouton": ("crouton",), "dumpling": ("knödel", "kloss", "klöße"),
    "rice": ("reis",), "pasta": ("nudel", "pasta", "spaghetti", "gnocchi"), "noodle": ("nudel",),
    "cheese": ("käse", "gouda", "parmesan", "emmentaler", "bergkäse", "feta", "mozzarella", "greyerzer", "cheddar"),
    "tomato": ("tomate",), "cucumber": ("gurke",), "olive": ("olive",), "avocado": ("avocado",),
    "salad": ("salat",), "lettuce": ("salat",), "corn": ("mais",), "bell pepper": ("paprika",),
    "mushroom": ("pilz", "champignon", "steinpilz"), "pea": ("erbse",), "bean": ("bohne",),
    "carrot": ("möhre", "karotte", "rüebli"), "potato": ("kartoffel", "gnocchi"), "onion": ("zwiebel",),
    "cream": ("sahne", "rahm", "crème", "creme", "schmand", "sauerrahm"),
    "sour cream": ("sauerrahm", "schmand", "crème"), "yoghurt": ("joghurt",),
    "egg": ("ei", "eier"), "bacon": ("speck",), "ham": ("schinken", "kassler", "kasseler"),
    "sausage": ("wurst", "würstchen"), "chicken": ("hähnchen", "huhn", "poulet"), "beef": ("rind",),
    "fish": ("fisch", "lachs", "forelle"), "shrimp": ("garnele", "crevette"),
    "mustard": ("senf",), "ketchup": (), "sauce": ("sauce", "soße"), "gravy": ("sauce", "soße", "bratensaft"),
}
# Forbidden whatever is in the list: the dish is shown as cooked, never styled with extras.
GARNISH_RE = re.compile(r"garnish\w*|\bsprigs?\b|\bswirls?\b|\bdrizzled?\b|\bside dish\b|\bgarniert\b|"
                        r"\bserved with a side\b|\bsprinkled with fresh\b", re.I)


def ingredient_text(ingredients: list[dict]) -> str:
    """Lower-case bag of words of all ingredient names and notes (German), for the 'is it in the recipe?' check."""
    parts = []
    for ing in ingredients or []:
        if isinstance(ing, dict):
            parts += [str(ing.get("name") or ""), str(ing.get("note") or "")]
    return " ".join(parts).lower()


def _mentions(term: str, text: str) -> bool:
    """German compounds count ('Speckwürfel' contains 'speck'); very short terms only at a word start ('Eier', not 'Zwiebeln')."""
    if len(term) < 4:
        return re.search(r"(?<![a-zäöüéèç])" + re.escape(term), text) is not None
    return term in text


def image_prompt_problems(prompt: str, ingredients: list[dict]) -> list[str]:
    """Problems with an image_prompt: German text, garnish/styling, or food that the recipe does not contain."""
    errs: list[str] = []
    p = prompt.lower()
    if re.search(r"[äöüß]", p):
        errs.append("image_prompt: must be English")
    g = GARNISH_RE.search(p)
    if g:
        errs.append(f"image_prompt: '{g.group(0).strip()}' – no garnish, side dish or sauce swirl, only the cooked dish")
    have = ingredient_text(ingredients)
    for term, german in EXTRA_FOOD_VOCAB.items():
        if re.search(rf"\b{re.escape(term)}(s|es)?\b", p) and not any(_mentions(w, have) for w in german):
            errs.append(f"image_prompt: mentions '{term}', which is not in the ingredient list")
    return errs


def image_components_problems(components, ingredients: list[dict]) -> list[str]:
    """`image_components` = ids of the ingredients you can actually SEE in the finished dish."""
    if not isinstance(components, list) or not components:
        return ["image_components: non-empty list of ingredient ids required"]
    by_id = {i.get("id"): i for i in (ingredients or []) if isinstance(i, dict)}
    errs, seen = [], set()
    for c in components:
        if not isinstance(c, str) or c not in by_id:
            errs.append(f"image_components: '{c}' is not an ingredient id of this recipe")
            continue
        if c in seen:
            errs.append(f"image_components: duplicate id {c}")
        seen.add(c)
        name = str(by_id[c].get("name") or "")
        if INVISIBLE_INGREDIENT_RE.search(name):
            errs.append(f"image_components: '{name}' is not visible in the finished dish (dissolved, seasoning or frying fat)")
    return errs


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_recipe(r: dict) -> list[str]:
    """Return a list of problems (empty list = valid). Structural validation only."""
    errs: list[str] = []
    if not isinstance(r, dict):
        return ["recipe is not an object"]
    for k in ("title", "intro", "serving_tip", "image_prompt"):
        if not isinstance(r.get(k), str) or not r[k].strip():
            errs.append(f"{k}: missing or empty string")
    sv = r.get("servings")
    if not (isinstance(sv, dict) and _is_num(sv.get("amount")) and sv["amount"] > 0 and isinstance(sv.get("unit"), str)):
        errs.append("servings: need {amount:number>0, unit:string}")
    tm = r.get("times")
    if not isinstance(tm, dict):
        errs.append("times: missing")
    else:
        for k in ("prep_min", "cook_min", "rest_min"):
            if tm.get(k) is not None and not _is_num(tm[k]):
                errs.append(f"times.{k}: number or null")
    ings = r.get("ingredients")
    ids: set[str] = set()
    if not isinstance(ings, list) or not ings:
        errs.append("ingredients: non-empty list required")
    else:
        for i, ing in enumerate(ings):
            p = f"ingredients[{i}]"
            if not isinstance(ing, dict):
                errs.append(f"{p}: not an object"); continue
            if not isinstance(ing.get("id"), str) or not ing["id"]:
                errs.append(f"{p}.id missing")
            elif ing["id"] in ids:
                errs.append(f"{p}.id duplicate {ing['id']}")
            else:
                ids.add(ing["id"])
            if not isinstance(ing.get("name"), str) or not ing["name"].strip():
                errs.append(f"{p}.name missing")
            q = ing.get("quantity")
            if q is not None and not (_is_num(q) and q > 0):
                errs.append(f"{p}.quantity must be number>0 or null")
            u = ing.get("unit")
            if u is not None and not isinstance(u, str):
                errs.append(f"{p}.unit must be string or null")
            elif isinstance(u, str) and u not in STANDARD_UNITS:
                errs.append(f"{p}.unit '{u}' not in standard unit list")
    ip = r.get("image_prompt")
    if isinstance(ip, str) and ip.strip():
        errs += image_prompt_problems(ip, ings if isinstance(ings, list) else [])
    if r.get("image_components") is not None:
        errs += image_components_problems(r["image_components"], ings if isinstance(ings, list) else [])
    steps = r.get("steps")
    if not isinstance(steps, list) or not steps:
        errs.append("steps: non-empty list required")
    else:
        for i, s in enumerate(steps):
            p = f"steps[{i}]"
            if not isinstance(s, dict):
                errs.append(f"{p}: not an object"); continue
            if not isinstance(s.get("text"), str) or not s["text"].strip():
                errs.append(f"{p}.text missing")
            uses = s.get("uses", [])
            if not isinstance(uses, list):
                errs.append(f"{p}.uses must be list")
            else:
                for u in uses:
                    if u not in ids:
                        errs.append(f"{p}.uses references unknown ingredient id '{u}'")
    return errs


def normalize_recipe(r: dict, rid: str, proposal_id: str | None) -> dict:
    """Fill defaults, number steps, assign ids. Mutates a copy."""
    r = dict(r)
    r["id"] = rid
    r["proposal_id"] = proposal_id
    r.setdefault("times", {})
    for k in ("prep_min", "cook_min", "rest_min"):
        r["times"].setdefault(k, None)
    r.setdefault("differentiation", "")
    r.setdefault("image_alt", None)
    r.setdefault("change_log", [])
    r["ai_label"] = True
    r["version"] = int(r.get("version", 1))
    r["image_path"] = r.get("image_path")
    for i, ing in enumerate(r.get("ingredients", []), 1):
        ing.setdefault("id", f"i{i}")
        ing.setdefault("group", None)
        ing.setdefault("note", None)
        ing.setdefault("quantity", None)
        ing.setdefault("unit", None)
    for n, s in enumerate(r.get("steps", []), 1):
        s["n"] = n
        s.setdefault("group", None)
        s.setdefault("uses", [])
        s.setdefault("temperature_c", None)
        s.setdefault("duration_min", None)
    return r


def validate_review(rv: dict) -> list[str]:
    errs = []
    if not isinstance(rv, dict) or "criteria" not in rv:
        return ["review: missing criteria"]
    for k in CRITERIA:
        c = rv["criteria"].get(k)
        if not isinstance(c, dict) or "pass" not in c:
            errs.append(f"criteria.{k} missing")
    return errs


def validate_nutrition(n: dict) -> list[str]:
    errs = []
    if n.get("reference") != "per_serving":
        errs.append("reference must be 'per_serving'")
    if not isinstance(n.get("ingredients"), list):
        errs.append("ingredients list missing")
    return errs
