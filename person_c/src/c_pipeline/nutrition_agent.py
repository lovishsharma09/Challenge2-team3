"""Nutrition Agent (step 8): match ingredients to the Swiss DB, convert units, compute per serving.

Principles (from the briefing):
  * every value traces to a database row or to a documented conversion rule,
  * every match is logged with the original ingredient, the replacement used and a confidence,
  * nothing is invented: unmatched / unconvertible ingredients are EXCLUDED and reported.
The LLM (optional) may only choose among database candidates the code retrieved.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from .config import ROOT
from .conversions import to_basis_amount
from .nutrition_db import FoodEntry, NutritionDB, normalize
from .schemas import SALT_PEPPER_RE

# Ingredients the search cannot resolve on its own are pinned here, so the same recipe always gives the same values.
OVERRIDES_JSON = ROOT / "assets" / "ingredient_overrides.json"

DROP_WORDS = {
    "frisch", "frische", "frischer", "frisches", "gemahlen", "gemahlene", "gehackt", "gehackte", "fein", "feine",
    "grob", "grobe", "gross", "grosse", "klein", "kleine", "mittelgross", "mittelgrosse", "geschalt", "geschalte",
    "bio", "ungespritzt", "ungespritzte", "nach", "belieben", "geschmack", "etwa", "ca", "evtl", "optional",
    "gewurfelt", "gewurfelte", "geraspelt", "geriebene", "geriebener", "gerieben", "weich", "kalt", "kalte", "warm",
    "heiss", "heisse", "zimmerwarm", "reif", "reife", "ganze", "ganz", "halbe", "halb", "dick", "dunn", "stuck",
}
PROCESSED = {"gekocht", "gebraten", "frittiert", "paniert", "konserve", "getrocknet", "gedunstet", "gegart",
             "geraucht", "eingelegt", "pur"}
# search-expansion aliases (query stem -> alternative DB wordings). Not data: only helps retrieval.
ALIASES = {
    "lauchzwiebel": ["fruhlingszwiebel", "zwiebel jung", "zwiebel"],
    "fruhlingszwiebel": ["lauchzwiebel", "zwiebel"],
    "weisswein": ["wein weiss", "weisswein"],
    "rotwein": ["wein rot", "rotwein"],
    "ei": ["huhnerei", "vollei", "ei ganz"],
    "eier": ["huhnerei", "vollei"],
    "sahne": ["rahm", "vollrahm", "schlagsahne", "rahm 35"],
    "schlagsahne": ["sahne", "rahm", "vollrahm"],
    "mohre": ["karotte", "rube"],
    "karotte": ["mohre", "rube"],
    "kartoffel": ["erdapfel", "kartoffeln"],
    "grunkohl": ["kohl grun", "federkohl", "krauskohl", "braunkohl"],
    "rosenkohl": ["kohlsprossen", "sprossenkohl"],
    "olivenol": ["ol olive", "olivenol"],
    "rapsol": ["ol raps", "rapsol"],
    "hahnchenbrust": ["huhn brust", "poulet brust", "hahnchen brust"],
    "entenbrust": ["ente brust", "entenfleisch"],
    "puderzucker": ["zucker puder", "staubzucker"],
    "zucker": ["haushaltszucker", "zucker weiss", "kristallzucker"],
    "weizenmehl": ["mehl weizen", "mehl"],
    "mehl": ["weissmehl", "weizenmehl", "mehl weizen"],
    "butter": ["butter", "kochbutter"],
    "mandel": ["mandeln", "mandel suss"],
    "gemusebruhe": ["bruhe gemuse", "bouillon gemuse"],
    "hefe": ["backhefe", "hefe frisch"],
    # added after the first real run (these five found no database entry); retrieval-only, the code still scores every hit
    "schmalz": ["schweineschmalz", "schweinefett", "schmalz"],
    "kassler": ["kasseler", "schweinefleisch gepokelt geraucht", "schweinefleisch kasseler"],
    "kasseler": ["kassler", "schweinefleisch gepokelt geraucht"],
    "hafergrutze": ["haferflocken", "hafer", "hafergrutze"],
    "muskat": ["muskatnuss", "muskat"],
    "muskatnuss": ["muskat"],
    "lorbeerblatt": ["lorbeer", "lorbeerblatter"],
    "lorbeerblatter": ["lorbeer", "lorbeerblatt"],
}


def stem(tok: str) -> str:
    for suf in ("innen", "chen", "ern", "en", "er", "es", "n", "e", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def clean_query(name: str) -> str:
    n = re.sub(r"\([^)]*\)", " ", name)
    n = normalize(n)
    toks = [t for t in re.split(r"[ ,/]+", n) if t and t not in DROP_WORDS and len(t) > 1]
    return " ".join(toks)


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[ ,/-]+", s) if t]


@dataclass
class Candidate:
    entry: FoodEntry
    score: float
    why: str


def _score_form(q: str, qstems: list[str], f: str, is_syn: bool) -> tuple[float, str]:
    if not f:
        return 0.0, ""
    ftoks = _tokens(f)
    fstems = [stem(t) for t in ftoks]
    head = f.split(",")[0].strip()
    if q == f:
        return (0.95 if is_syn else 1.0), "exakter Treffer" + (" (Synonym)" if is_syn else "")
    if q == head:
        return (0.88 if is_syn else 0.92), "Treffer auf Hauptbezeichnung" + (" (Synonym)" if is_syn else "")
    if qstems and all(s in fstems for s in qstems):
        extra = len(fstems) - len(qstems)
        sc = 0.82 - 0.03 * min(extra, 5)
        if any(p in ftoks for p in PROCESSED) and not any(p in q for p in PROCESSED):
            sc -= 0.1
        if "roh" in ftoks:
            sc += 0.03
        return sc, "alle Suchbegriffe im Datenbanknamen"
    # compound containment: 'lachsfilet' vs 'lachs'
    hs = stem(_tokens(head)[0]) if _tokens(head) else ""
    q1 = qstems[-1] if qstems else ""
    if len(hs) >= 4 and q1 and (q1.startswith(hs) or q1.endswith(hs)) and len(qstems) == 1:
        return 0.72 - (0.0 if not is_syn else 0.03), "Wortbestandteil (Kompositum)"
    r = SequenceMatcher(None, q, head).ratio()
    return r * 0.8, f"Ähnlichkeit {r:.2f}"


def retrieve(db: NutritionDB, ingredient_name: str, k: int = 8) -> list[Candidate]:
    q = clean_query(ingredient_name)
    if not q:
        return []
    qstems = [stem(t) for t in _tokens(q)]
    queries = [(q, qstems, 1.0)]
    for key in ({q} | set(qstems)):
        for alt in ALIASES.get(key, []):
            queries.append((alt, [stem(t) for t in _tokens(alt)], 0.97))
    best: dict[str, Candidate] = {}
    for e in db.entries:
        forms = [(e.norm_name, False)] + [(s, True) for s in e.norm_synonyms]
        top = (0.0, "")
        for qq, qs, w in queries:
            for f, is_syn in forms:
                sc, why = _score_form(qq, qs, f, is_syn)
                sc *= w
                if sc > top[0]:
                    top = (sc, why + ("" if qq == q else f" via Alias '{qq}'"))
        if top[0] > 0.3:
            # prefer raw / shorter entries on ties
            tie = (0.002 if "roh" in e.norm_name else 0.0) - 0.0001 * len(e.norm_name)
            best[e.db_id] = Candidate(e, top[0] + tie, top[1])
    return sorted(best.values(), key=lambda c: -c.score)[:k]


@dataclass
class Match:
    entry: FoodEntry | None
    confidence: float
    method: str            # exact | closest | llm | none
    why: str
    candidates: list[str]


def _match_core(db: NutritionDB, ing: dict, llm=None) -> Match:
    cands = retrieve(db, ing["name"])
    names = [f"{c.entry.name} ({c.score:.2f})" for c in cands[:5]]
    if not cands:
        return Match(None, 0.0, "none", "keine Kandidaten in der Datenbank", [])
    top = cands[0]
    if top.score >= 0.9 or llm is None:
        if top.score >= 0.55:
            return Match(top.entry, round(min(top.score, 1.0), 2), "exact" if top.score >= 0.9 else "closest", top.why, names)
        if llm is None:
            return Match(None, round(top.score, 2), "none", f"bester Kandidat '{top.entry.name}' zu unsicher ({top.score:.2f})", names)
    # ambiguous: let the LLM choose among retrieved candidates only
    try:
        payload = [{"idx": i, "name": c.entry.name, "synonyms": c.entry.synonyms[:4],
                    "category": c.entry.category, "code_score": round(c.score, 2)} for i, c in enumerate(cands)]
        prompt = (f"TASK: nutrition_match\nIngredient: {ing['name']}"
                  f" | note: {ing.get('note')} | amount: {ing.get('quantity')} {ing.get('unit') or ''}\n"
                  f"Candidates (JSON): {payload}\n"
                  'Choose the nutritionally closest raw/plain database entry. Reply JSON: '
                  '{"choice": <idx or null>, "confidence": <0..1>, "reason": "<short German reason>"}. '
                  "Choose null if none is a sensible match. Never invent entries.")

        def _v(o):
            if not isinstance(o, dict) or "choice" not in o:
                return ["need {choice, confidence, reason}"]
            ch = o["choice"]
            if ch is not None and not (isinstance(ch, int) and 0 <= ch < len(cands)):
                return ["choice must be an index of the candidate list or null"]
            return []
        res = llm.chat_json("You match recipe ingredients to food composition database entries. Output JSON only.",
                            prompt, validate=_v, retries=1, temperature=0.0)
        if res["choice"] is not None:
            c = cands[res["choice"]]
            conf = float(res.get("confidence", 0.6))
            blended = round(0.5 * min(c.score, 1.0) + 0.5 * conf, 2)
            if blended >= 0.5:
                return Match(c.entry, blended, "llm", f"LLM-Auswahl unter DB-Kandidaten: {res.get('reason', '')}", names)
        return Match(None, 0.0, "none", "LLM sieht keinen passenden Datenbankeintrag", names)
    except Exception:  # LLM unavailable: fall back to the code decision
        if top.score >= 0.55:
            return Match(top.entry, round(top.score, 2), "closest", top.why + " (ohne LLM)", names)
        return Match(None, round(top.score, 2), "none", f"bester Kandidat '{top.entry.name}' zu unsicher", names)


TINY_SPICE = re.compile(r"lorbeer|muskat|nelke|wacholder|pfeffer|piment|zimt|kurkuma|curry|paprikapulver|kümmel|kreuzkümmel|chili|vanille|safran|"
                        r"thymian|rosmarin|majoran|oregano|salbei|petersilie|schnittlauch|dill|basilikum|koriander|ingwerpulver", re.I)


def tiny_grams(ing: dict) -> float | None:
    """Documented estimate for spice-sized amounts without a database match (None = not a tiny spice amount)."""
    from .conversions import PIECE_G, UNIT_FIXED_G
    if not TINY_SPICE.search(ing["name"]) or not ing.get("quantity"):
        return None
    q, u = float(ing["quantity"]), ing.get("unit")
    if u in ("Prise", "Msp."):
        return q * UNIT_FIXED_G[u][0]
    if u == "g":
        return q
    if u in (None, "Blatt", "Stück") and "lorbeer" in ing["name"].lower():
        return q * PIECE_G["lorbeerblatt"]
    if u in ("Stiel", "Zweig"):
        return q * UNIT_FIXED_G[u][0]
    return None


def _expand_and_retry(db: NutritionDB, ing: dict, llm) -> Match | None:
    """No candidate found: ask the LLM only for alternative SEARCH TERMS (database-style names), then match them in code."""
    if llm is None:
        return None
    prompt = (f"TASK: nutrition_terms\nIngredient: {ing['name']} | note: {ing.get('note')}\n"
              "Give up to 4 alternative German search terms for this ingredient as it could be named in the Swiss food composition "
              "database (generic names, singular, e.g. 'Schweineschmalz', 'Haferflocken', 'Kasseler, Schweinefleisch, geräuchert'). "
              'Reply JSON only: {"terms": ["..."]}')
    try:
        res = llm.chat_json("You translate recipe ingredients into generic food database names. Output JSON only.", prompt,
                            validate=lambda o: [] if isinstance(o, dict) and isinstance(o.get("terms"), list) else ["need {terms: [..]}"],
                            retries=1, temperature=0.0)
    except Exception:  # noqa: BLE001
        return None
    best = None
    for term in [str(t) for t in res["terms"]][:4]:
        cands = retrieve(db, term, 4)
        if cands and (best is None or cands[0].score > best[0].score):
            best = (cands[0], term)
    if best and best[0].score >= 0.85:
        c, term = best
        return Match(c.entry, round(0.8 * min(c.score, 1.0), 2), "alias", f"über Suchbegriff '{term}' (LLM-Vorschlag, im Code geprüft): {c.why}", [f"{c.entry.name} ({c.score:.2f})"])
    return None


def _closest_category(db: NutritionDB, ing: dict, llm) -> Match | None:
    """Last resort for MATERIAL ingredients (>= 50 g) without a database entry: the briefing allows 'the closest suitable
    database entry' if it is clearly labelled with original, replacement and confidence. The LLM only proposes broader
    category search terms and then picks among candidates that the code retrieved; confidence is capped at 0.5."""
    if llm is None or _approx_grams(ing) < 50:
        return None
    try:
        terms = llm.chat_json("You translate recipe ingredients into broader food categories. Output JSON only.",
                              f"TASK: nutrition_category\nIngredient: {ing['name']} | note: {ing.get('note')}\n"
                              "Give up to 4 BROADER German category search terms as used in a Swiss food composition database "
                              "(e.g. for 'Kassler': 'Schweinefleisch', 'Schinken', 'Rauchfleisch'). Reply JSON only: {\"terms\": [\"...\"]}",
                              validate=lambda o: [] if isinstance(o, dict) and isinstance(o.get("terms"), list) else ["need {terms: [..]}"],
                              retries=1, temperature=0.0)["terms"]
        pool: dict = {}
        for t in [str(x) for x in terms][:4]:
            for c in retrieve(db, t, 6):
                if c.score >= 0.5:
                    pool.setdefault(c.entry.db_id, c)
        cands = sorted(pool.values(), key=lambda c: -c.score)[:10]
        if not cands:
            return None
        payload = [{"idx": i, "name": c.entry.name, "category": c.entry.category} for i, c in enumerate(cands)]
        res = llm.chat_json("You pick the nutritionally closest database entry. Output JSON only.",
                            f"TASK: nutrition_closest\nIngredient: {ing['name']} | note: {ing.get('note')}\nCandidates (JSON): {payload}\n"
                            'Pick the entry with the most similar nutrition (same kind of food, similar fat/protein). Reply JSON: '
                            '{"choice": <idx or null>, "confidence": <0..1>, "reason": "<short German reason>"}. null if none is similar.',
                            validate=lambda o: [] if isinstance(o, dict) and "choice" in o and (o["choice"] is None or (isinstance(o["choice"], int) and 0 <= o["choice"] < len(cands))) else ["need {choice, confidence, reason}"],
                            retries=1, temperature=0.0)
        if res["choice"] is None:
            return None
        c = cands[res["choice"]]
        conf = round(min(0.5, 0.6 * float(res.get("confidence", 0.5))), 2)
        return Match(c.entry, conf, "closest_category",
                     f"nächstliegender Eintrag (Annahme; kein exakter Treffer, Kategorie-Suche): {res.get('reason', '')}",
                     [f"{x.entry.name} ({x.score:.2f})" for x in cands[:5]])
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=4)
def load_overrides(path: str | None = None) -> dict:
    """Fixed ingredient -> db_id assignments (assets/ingredient_overrides.json), keyed by normalized name."""
    p = Path(path or OVERRIDES_JSON)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {normalize(k): v for k, v in (data.get("overrides") or {}).items()}


def override_match(db: NutritionDB, ing: dict, overrides: dict | None = None) -> Match | None:
    """A pinned assignment beats every search: the LLM would pick a different 'closest entry' on every run."""
    table = load_overrides() if overrides is None else overrides
    for key in (normalize(ing["name"]), clean_query(ing["name"])):
        o = table.get(key)
        if not o:
            continue
        entry = db.by_id.get(str(o["db_id"]))
        if entry is None:                      # a different database version: fall back to the normal search
            return None
        why = o.get("why") or f"nächstliegender Eintrag (Annahme; feste Zuordnung): {entry.name}"
        return Match(entry, float(o.get("confidence", 0.5)), o.get("method", "closest_category"), why,
                     [f"{entry.name} (feste Zuordnung)"])
    return None


def match_ingredient(db: NutritionDB, ing: dict, llm=None, overrides: dict | None = None) -> Match:
    pinned = override_match(db, ing, overrides)
    if pinned is not None:
        return pinned
    m = _match_core(db, ing, llm)
    if m.entry is None:
        alt = _expand_and_retry(db, ing, llm) or _closest_category(db, ing, llm)
        if alt is not None:
            return alt
    return m


NUTRIENT_KEYS = ["kcal", "kj", "fat_g", "sat_fat_g", "carbs_g", "sugar_g", "fiber_g", "protein_g", "salt_g"]


def round_nutrient(key: str, v: float | None) -> float | int | None:
    if v is None:
        return None
    if key in ("kcal", "kj"):
        return int(round(v))
    return round(v, 1) if v < 10 else int(round(v))


def _approx_grams(ing: dict) -> float:
    """Rough mass of an UNMATCHED ingredient (only to decide whether the gap is material; never used for nutrition values)."""
    q, u = ing.get("quantity"), ing.get("unit")
    if not q:
        return 0.0
    q = float(q)
    return {"g": q, "kg": q * 1000, "ml": q, "l": q * 1000, "cl": q * 10, "EL": q * 15, "TL": q * 5}.get(u, q * 60 if u in (None, "Stück") else q * 10)


def compute_nutrition(recipe: dict, db: NutritionDB, llm=None) -> dict:
    servings = float(recipe["servings"]["amount"])
    rows, unmatched, notes, negligible = [], [], [], []
    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    missing_mass = {k: 0.0 for k in NUTRIENT_KEYS}
    matched_mass = 0.0
    weighted_conf = 0.0
    need_calc = 0
    for ing in recipe["ingredients"]:
        orig = " ".join(x for x in [f"{ing['quantity']:g}" if ing.get("quantity") else "", ing.get("unit") or "", ing["name"]] if x)
        if ing.get("note"):
            orig += f", {ing['note']}"
        base = {"original": orig, "ingredient_id": ing["id"]}
        if ing.get("quantity") is None:
            if SALT_PEPPER_RE.match(ing["name"]):
                notes.append(f"{orig}: Salz/Pfeffer ohne Menge (nach Geschmack) nicht eingerechnet")
            else:
                unmatched.append(base | {"reason": "keine Mengenangabe – nicht berechenbar"})
            continue
        need_calc += 1
        m = match_ingredient(db, ing, llm)
        if m.entry is None:
            tg = tiny_grams(ing)
            if tg is not None and tg <= 2.0:
                need_calc -= 1
                negligible.append(base | {"estimated_grams": round(tg, 2), "reason": "Gewürzmenge ≤ 2 g, kein Datenbanktreffer – vernachlässigt"})
                notes.append(f"{orig}: ca. {tg:.1f} g Gewürz, nicht eingerechnet (vernachlässigbar, dokumentierte Annahme)")
                continue
            unmatched.append(base | {"reason": m.why, "candidates": m.candidates})
            continue
        conv = to_basis_amount(float(ing["quantity"]), ing.get("unit"), ing["name"], ing.get("note"), m.entry)
        if conv.basis_amount is None:
            unmatched.append(base | {"reason": conv.rule, "db_name": m.entry.name, "candidates": m.candidates})
            continue
        factor = conv.basis_amount / m.entry.basis_amount
        contrib = {}
        for k in NUTRIENT_KEYS:
            v = m.entry.nutrients.get(k)
            if v is None:
                missing_mass[k] += conv.grams or conv.basis_amount
                contrib[k] = None
            else:
                totals[k] += v * factor
                contrib[k] = v * factor
        mass = conv.grams or conv.basis_amount
        matched_mass += mass
        conf = round(m.confidence * conv.factor, 2)
        weighted_conf += conf * mass
        rows.append(base | {
            "db_id": m.entry.db_id, "db_name": m.entry.name, "db_basis": m.entry.basis_text or f"pro {m.entry.basis_amount:g}{m.entry.basis_unit}",
            "amount_in_basis": round(conv.basis_amount, 2), "basis_unit": conv.basis_unit,
            "grams": round(mass, 1), "conversion": conv.rule, "assumption": conv.assumption,
            "match": m.method, "match_reason": m.why, "confidence": conf,
            "kcal": round(contrib["kcal"], 1) if contrib["kcal"] is not None else None,
        })
    # An unmatched ingredient of real weight would make every total an under-estimate -> do NOT present partial sums.
    ing_by_id = {i["id"]: i for i in recipe["ingredients"]}
    unmatched_mass = sum(_approx_grams(ing_by_id[u["ingredient_id"]]) for u in unmatched if u.get("ingredient_id") in ing_by_id)
    total_mass = matched_mass + unmatched_mass
    incomplete = bool(total_mass) and unmatched_mass / total_mass > 0.05
    per_serving: dict[str, float | int | None] = {}
    for k in NUTRIENT_KEYS:
        if incomplete or matched_mass <= 0 or (missing_mass[k] / matched_mass) > 0.05:
            per_serving[k] = None
        else:
            per_serving[k] = round_nutrient(k, totals[k] / servings)
    for row in rows:
        if row["match"] == "closest_category":
            notes.append(f"{row['original']}: nächstliegender Eintrag (Annahme) – '{row['db_name']}', Konfidenz {row['confidence']}")
    if incomplete:
        notes.append("Nährwerte NICHT ausgewiesen: unvollständig, da für " + ", ".join(u["original"] for u in unmatched)
                     + f" kein Datenbanktreffer vorliegt (ca. {unmatched_mass / total_mass:.0%} der Zutatenmasse).")
    included = len(rows)
    coverage = round(included / need_calc, 2) if need_calc else 0.0
    overall_conf = round(weighted_conf / matched_mass, 2) if matched_mass else 0.0
    # A "closest category" row is an assumption, not a real hit -> the label can never be "hoch".
    assumed = any(row["match"] == "closest_category" for row in rows)
    quality = ("unvollständig" if incomplete else
               "hoch" if coverage == 1 and overall_conf >= 0.75 and not assumed else
               "mittel" if coverage >= 0.8 and overall_conf >= 0.55 else "niedrig")
    if db.is_fixture:
        notes.append("TESTDATEN: synthetische Fixture-Werte, keine echten Datenbankwerte")
    return {
        "recipe_id": recipe["id"], "reference": "per_serving", "servings": servings,
        "ingredients": rows, "unmatched": unmatched, "negligible": negligible,
        "per_serving": per_serving, "incomplete": incomplete,
        "coverage": {"ingredients_calculated": included, "ingredients_needing_calc": need_calc,
                     "share": coverage, "mean_confidence": overall_conf, "quality": quality},
        "notes": notes,
        "db": {"source": db.source, "version": db.version, "synthetic_fixture": db.is_fixture},
    }
