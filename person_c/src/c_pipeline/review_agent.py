"""Stage 07 – Review Agent: deterministic code checks + LLM judgement against the 8 review criteria.

Code checks cover everything that can be verified mechanically (completeness of quantities, ingredient use,
quantity consistency between list and steps, EL/TL, step order, structure, archive/sibling similarity).
The LLM adds culinary logic, plausibility, brand fit and food safety. Result format: CONTRACTS.md (review.json).
"""
from __future__ import annotations
import json
import re

from .recipe_agent import SYSTEM, brand_text, fill, load_prompt
from .schemas import CRITERIA, EXTRA_CRITERIA, SALT_PEPPER_RE

UNITS = r"(kg|g|ml|cl|l|EL|TL|Prise|Msp\.|Stück|Bund|Stiel|Zweig|Zehe|Scheibe|Dose|Pck\.|Blatt|Kopf|Handvoll|Glas|Becher)"
NUM = r"(\d+(?:[.,]\d+)?\s?[½¼¾]?|[½¼¾])"
SPICES = re.compile(r"zimt|kurkuma|paprikapulver|kreuzkümmel|kümmel|majoran|muskat|chili|curry|nelken|piment|koriander gemahlen|ingwerpulver", re.I)
PREHEAT = re.compile(r"vorheizen|auf \d+ Grad", re.I)
BAKING = re.compile(r"im (vorgeheizten )?(Backofen|Ofen)|backen|überbacken|gratinieren", re.I)
SERVE = re.compile(r"servieren|anrichten|auftragen", re.I)
COOK_VERB = re.compile(r"braten|kochen|köcheln|backen|garen|schmoren|anbraten", re.I)


def _stem(name: str) -> str:
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", re.sub(r"\(.*?\)", "", name))
    w = (words[-1] if words else name).lower()
    return w[:6] if len(w) > 6 else w[:max(4, len(w) - 1)]


def _tofloat(s: str) -> float:
    s = s.strip()
    frac = {"½": .5, "¼": .25, "¾": .75}
    total = 0.0
    for ch, v in frac.items():
        if ch in s:
            total += v
            s = s.replace(ch, "")
    s = s.strip().replace(",", ".")
    return total + (float(s) if s else 0.0)


def _fmt(q: float) -> str:
    return f"{q:g}"


def _is_salt_pepper(ing: dict) -> bool:
    return bool(SALT_PEPPER_RE.match(ing["name"]))


def _add(f: dict, crit: str, severity: str, msg: str, where: str | None = None):
    f.setdefault(crit, []).append({"severity": severity, "message": msg, "where": where})


def code_checks(r: dict, sibling: dict | None = None, archive_matches: list[dict] | None = None) -> dict[str, list[dict]]:
    f: dict[str, list[dict]] = {}
    ings, steps = r["ingredients"], r["steps"]
    texts = [s["text"] for s in steps]
    alltext = " ".join(texts)
    low = alltext.lower()
    servings = float((r.get("servings") or {}).get("amount") or 1)

    # 1 title -------------------------------------------------------------------------------
    t = r["title"].strip()
    if len(t) < 4 or len(t) > 75:
        _add(f, "title", "error", f"Titel hat unpassende Länge ({len(t)} Zeichen)")
    if re.search(r"rezept|kitas|\.\.\.|!!", t, re.I):
        _add(f, "title", "warning", "Titel enthält Füllwörter oder Satzzeichen")

    # 2 subheadings ---------------------------------------------------------------------------
    ig = [i.get("group") for i in ings if not _is_salt_pepper(i)]
    if any(ig) and not all(ig):
        _add(f, "subheadings", "warning", "Zutaten teils mit, teils ohne Zwischenüberschrift")
    if len({g for g in ig if g}) == 1:
        _add(f, "subheadings", "warning", "Nur eine Zutatengruppe – Zwischenüberschrift überflüssig")
    sg = [s.get("group") for s in steps]
    if any(sg) and not all(sg):
        _add(f, "subheadings", "warning", "Schritte teils mit, teils ohne Zwischenüberschrift")

    # 3 quantity plausibility -------------------------------------------------------------------
    grams = 0.0
    for i in ings:
        q, u = i.get("quantity"), i.get("unit")
        if q:
            grams += {"g": q, "kg": q * 1000, "ml": q, "l": q * 1000, "cl": q * 10, "EL": q * 15, "TL": q * 5}.get(u, 0)
    per = grams / servings if servings else 0
    if (r["servings"].get("unit") or "").lower().startswith("portion") and grams:
        if per < 150:
            _add(f, "quantity_plausibility", "warning", f"Sehr kleine Portion: ca. {per:.0f} g pro Portion (nur g/ml/EL/TL gezählt)")
        if per > 1100:
            _add(f, "quantity_plausibility", "warning", f"Sehr große Portion: ca. {per:.0f} g pro Portion")
    for i in ings:
        q, u, n = i.get("quantity"), i.get("unit"), i["name"]
        if re.match(r"\s*salz", n, re.I) and q and ((u == "TL" and q / servings * 4 > 2) or (u == "EL")):
            _add(f, "quantity_plausibility", "error", f"Salzmenge unplausibel hoch: {_fmt(q)} {u} für {_fmt(servings)} Portionen", n)
        if SPICES.search(n) and u == "EL" and q and q / servings * 4 >= 1:
            _add(f, "quantity_plausibility", "warning", f"Gewürz in EL statt TL/Msp.? {_fmt(q)} EL {n}", n)

    # 4 completeness of quantities -----------------------------------------------------------------
    for i in ings:
        if not i.get("quantity") and not _is_salt_pepper(i):
            _add(f, "quantity_completeness", "error", f"Zutat ohne Mengenangabe: {i['name']}", i["name"])

    # 5 all ingredients used (and both directions where detectable) -----------------------------------
    used_ids = {u for s in steps for u in s.get("uses", [])}
    for i in ings:
        st = _stem(i["name"])
        if i["id"] not in used_ids and st not in low:
            _add(f, "all_ingredients_used", "error", f"Zutat wird in keinem Schritt verwendet: {i['name']}", i["name"])
        elif i["id"] not in used_ids:
            _add(f, "all_ingredients_used", "warning", f"'{i['name']}' steht im Schritttext, aber nicht in `uses`", i["name"])
        elif st not in low:
            _add(f, "all_ingredients_used", "warning", f"'{i['name']}' ist in `uses` verlinkt, wird im Schritttext aber nicht genannt", i["name"])

    # 6 consistency of quantities/units (list vs. steps, split amounts) ---------------------------------
    for i in ings:
        q, u = i.get("quantity"), i.get("unit")
        if not q:
            continue
        st = _stem(i["name"])
        pat = re.compile(rf"{NUM}\s*{UNITS}?\s+(?:[\wäöüÄÖÜß\-]+\s+){{0,2}}?{re.escape(st)}", re.I)
        ments = [(_tofloat(m.group(1)), (m.group(2) or None)) for m in pat.finditer(alltext)]
        if not ments:
            continue
        same = sum(v for v, mu in ments if mu == u or (mu is None and u is None))
        other_units = {mu for v, mu in ments if mu != u}
        if other_units:
            _add(f, "units_consistent", "warning", f"{i['name']}: Einheit im Schritt ({', '.join(str(x) for x in other_units)}) weicht von der Liste ({u}) ab", i["name"])
        if same > q * 1.01 + 0.01:
            _add(f, "units_consistent", "error", f"{i['name']}: Schritte nennen zusammen {_fmt(same)} {u or ''}, die Zutatenliste nur {_fmt(q)} {u or ''}".replace("  ", " "), i["name"])
        elif same and same < q * 0.95:
            rest = re.search(rf"(übrig|restlich|rest\b)\w*\s+(?:[\wäöüÄÖÜß\-]+\s+){{0,2}}{re.escape(st)}", alltext, re.I)
            if not rest:
                _add(f, "units_consistent", "error", f"{i['name']}: Teilmengen in den Schritten ({_fmt(same)}) ergeben nicht die Listenmenge ({_fmt(q)}); kein Hinweis auf 'übrige/restliche' Menge", i["name"])

    # 7 EL / TL ------------------------------------------------------------------------------------------
    for i in ings:
        if i.get("unit") in ("EL", "TL"):
            other = "TL" if i["unit"] == "EL" else "EL"
            st = _stem(i["name"])
            if re.search(rf"\d[\d,.½¼¾]*\s*{other}\s+(?:[\wäöüÄÖÜß\-]+\s+){{0,2}}?{re.escape(st)}", alltext, re.I):
                _add(f, "tbsp_tsp", "error", f"{i['name']}: Liste {i['unit']}, Schritt nennt {other}", i["name"])
    if re.search(r"\bEßlöffel|\bEsslöffel|\bTeelöffel", alltext):
        _add(f, "tbsp_tsp", "warning", "Ausgeschriebene Löffelangabe – einheitlich EL/TL verwenden")

    # 8 step order -----------------------------------------------------------------------------------------
    first_bake = next((n for n, s in enumerate(texts) if BAKING.search(s) and not PREHEAT.search(s)), None)
    pre = next((n for n, s in enumerate(texts) if PREHEAT.search(s)), None)
    if first_bake is not None and pre is not None and pre > first_bake:
        _add(f, "step_order", "error", f"Backofen wird erst in Schritt {pre + 1} vorgeheizt, aber bereits in Schritt {first_bake + 1} benutzt")
    if first_bake is not None and pre is None and "ofen" in low:
        _add(f, "step_order", "warning", "Backofen wird benutzt, aber nirgends vorgeheizt")
    for n, s_ in enumerate(texts):
        sents = re.split(r"(?<=[.!?])\s+", s_)
        k = next((x for x, se in enumerate(sents) if SERVE.search(se)), None)
        if k is not None and any(COOK_VERB.search(se) for se in sents[k + 1:]):
            _add(f, "step_order", "error", f"Schritt {n + 1}: Servieren steht vor weiteren Garvorgängen")
    srv = [n for n, s in enumerate(texts) if SERVE.search(s)]
    if srv and srv[0] < len(texts) - 1 and any(COOK_VERB.search(s) for s in texts[srv[0] + 1:]):
        _add(f, "step_order", "warning", f"Servieren in Schritt {srv[0] + 1}, danach folgen noch Garschritte")

    # extras: completeness / brand / differentiation -----------------------------------------------------------
    if not (r.get("intro") or "").strip():
        _add(f, "completeness", "error", "Einleitung fehlt")
    if not (r.get("serving_tip") or "").strip():
        _add(f, "completeness", "error", "Serviertipp fehlt")
    tm = r.get("times") or {}
    if not any(tm.get(k) for k in ("prep_min", "cook_min", "rest_min")):
        _add(f, "completeness", "error", "Keine Zubereitungs-/Garzeit angegeben")
    if BAKING.search(alltext) and not re.search(r"\d+\s*Grad", alltext):
        _add(f, "completeness", "error", "Ofenschritt ohne Temperaturangabe")
    if len(steps) < 3:
        _add(f, "completeness", "warning", "Weniger als 3 Zubereitungsschritte")
    n_ing = sum(1 for i in ings if not _is_salt_pepper(i))
    if n_ing > 20:
        _add(f, "brand_fit", "error", f"Zu lange Zutatenliste ({n_ing} Zeilen) – Marke: keine langen Zutatenlisten")
    elif n_ing > 16:
        _add(f, "brand_fit", "warning", f"Lange Zutatenliste ({n_ing} Zeilen; Archiv-Median 12)")
    if sibling:
        a = {_stem(i["name"]) for i in ings}
        b = {_stem(i["name"]) for i in sibling["ingredients"]}
        j = len(a & b) / len(a | b) if a | b else 0
        if j >= 0.65:
            _add(f, "differentiation", "warning", f"Zutaten überschneiden sich zu {j:.0%} mit dem Schwesterrezept '{sibling['title']}'")
    for m in (archive_matches or [])[:3]:
        if m["similarity"] >= 0.5:
            _add(f, "differentiation", "warning", f"Sehr ähnlich zu Archivrezept '{m['title']}' ({m['modified']}, Ähnlichkeit {m['similarity']})")
    return f


def _validate_review(obj) -> list[str]:
    if not isinstance(obj, dict) or not isinstance(obj.get("criteria"), dict):
        return ["root must contain `criteria` object"]
    errs = []
    for k in CRITERIA:
        v = obj["criteria"].get(k)
        if not isinstance(v, dict) or not isinstance(v.get("pass"), bool) or not isinstance(v.get("issues", []), list):
            errs.append(f"criteria.{k} must be {{pass: bool, issues: [str], fix: str|null}}")
    return errs


def review_recipe(client, recipe: dict, sibling: dict | None, archive_matches: list[dict], brand_rules: dict,
                  iteration: int, round_type: str = "auto", editor_comment: str | None = None) -> dict:
    findings = code_checks(recipe, sibling, archive_matches)
    llm_used, llm = True, {"criteria": {}, "extras": {}}
    try:
        prompt = fill(load_prompt("review_llm.md"), RECIPE_ID=recipe["id"],
                      RECIPE=json.dumps({k: recipe[k] for k in ("title", "intro", "servings", "times", "ingredients", "steps", "serving_tip")}, ensure_ascii=False, indent=1),
                      SIBLING=json.dumps({"title": sibling["title"], "ingredients": [i["name"] for i in sibling["ingredients"]]}, ensure_ascii=False) if sibling else "(none)",
                      ARCHIVE="\n".join(f"- {m['title']} ({m['modified']}, Ähnlichkeit {m['similarity']})" for m in archive_matches) or "(none)",
                      BRAND=brand_text(brand_rules), FINDINGS=json.dumps(findings, ensure_ascii=False))
        llm = client.chat_json(SYSTEM, prompt, validate=_validate_review, retries=2, temperature=0.1)
    except Exception as e:  # noqa: BLE001 – a missing LLM verdict must not hide the code findings
        llm_used = False
        llm_error = str(e)[:200]

    def merge(key: str, source: dict) -> dict:
        items = findings.get(key, [])
        errs = [x["message"] for x in items if x["severity"] == "error"]
        warns = [f"Hinweis: {x['message']}" for x in items if x["severity"] == "warning"]
        lv = (source or {}).get(key) or {}
        issues = errs + [f"[LLM] {m}" for m in lv.get("issues", [])] + warns
        ok = not errs and lv.get("pass", True)
        fix = lv.get("fix") or ("; ".join(errs) if errs else None)
        return {"pass": bool(ok), "issues": issues, "fix": None if ok else fix}

    crit = {k: merge(k, llm.get("criteria", {})) for k in CRITERIA}
    extras = {k: merge(k, llm.get("extras", {})) for k in EXTRA_CRITERIA}
    failing = [(k, v) for k, v in {**crit, **extras}.items() if not v["pass"]]
    report = "\n".join(f"{n}. [{k}] " + " | ".join(i for i in v["issues"] if not i.startswith("Hinweis")) + (f" → Korrektur: {v['fix']}" if v["fix"] else "")
                       for n, (k, v) in enumerate(failing, 1))
    out = {"recipe_id": recipe["id"], "iteration": iteration, "round_type": round_type, "editor_comment": editor_comment,
           "recipe_version": recipe.get("version", 1), "criteria": crit, "extras": extras,
           "overall": "revise" if failing else "pass", "correction_report": report,
           "code_findings": findings, "archive_matches": archive_matches, "llm_used": llm_used}
    if not llm_used:
        out["llm_error"] = llm_error
    return out
