"""Recipe archive (SharePoint export: ~5000 censhare/DCX XML files).

Used for (a) the Review Agent's differentiation check, (b) style examples for the Recipe Agent and
(c) proving the renderer works for ARCHIVE recipes, not only for our generated ones
(template requirement "Wiederverwendbarkeit").

Newer archive files carry a `CustomStructuredRecipeJson` blob (clean data). Older files only have XML
attributes; most of those still carry `plural` (= ingredient name) and `unit` attributes. Files whose
ingredient names exist only as topic ids need the SQL topic map (`load_topicmap`) – otherwise they are
skipped for similarity (flag `names_resolved: false`).
"""
from __future__ import annotations
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

NS = {"d": "http://www.digicol.com/xmlns/dcx"}
_D = "{http://www.digicol.com/xmlns/dcx}"


def _txt(el) -> str | None:
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _num(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def load_topicmap(sql_zip: str | Path) -> dict[str, str]:
    """topic id -> display name from rezepte_export_topicmap.sql(.zip). Best effort (regex over INSERT rows)."""
    p = Path(sql_zip)
    if p.suffix == ".zip":
        with zipfile.ZipFile(p) as z:
            name = next(n for n in z.namelist() if n.endswith(".sql"))
            text = z.read(name).decode("utf-8", "replace")
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
    s = r"'((?:[^'\\]|\\.|'')*)'"
    rx = re.compile(rf"\(\s*\d+\s*,\s*{s}\s*,\s*{s}\s*,\s*(NULL|'(?:[^'\\]|\\.|'')*')\s*,\s*{s}\s*\)")
    out: dict[str, str] = {}
    for m in rx.finditer(text):
        topic, name, variant = m.group(1), m.group(2), m.group(3)
        if variant == "NULL" and topic not in out:
            out[topic] = name.replace("\\'", "'").replace("''", "'")
    return out


def parse_archive_xml(src: str | Path | bytes, topicmap: dict[str, str] | None = None) -> dict | None:
    """Parse one archive file into a normalized record (see keys below). Returns None if not a recipe."""
    try:
        root = ET.parse(io.BytesIO(src)).getroot() if isinstance(src, bytes) else ET.parse(str(src)).getroot()
    except ET.ParseError:
        return None
    head = root.find("d:head", NS)
    if head is None:
        return None
    topicmap = topicmap or {}
    rec: dict = {
        "id": root.get("id"),
        "created": _txt(root.find("d:created", NS)),
        "modified": _txt(root.find("d:modified", NS)),
        "title": _txt(head.find("d:Title", NS)) or _txt(head.find("d:Headline", NS)),
        "thesaurus": [e.get("topic") for e in head.findall("d:CustomRecipeThesaurs", NS)],
        "structured": False, "names_resolved": True,
    }
    blob = _txt(head.find("d:CustomStructuredRecipeJson", NS))
    if blob:
        try:
            d = json.loads(blob)
            h = d.get("recipe_header") or {}
            rec.update(structured=True, title=h.get("recipe_headline") or rec["title"],
                       servings=h.get("servings"), times=h.get("preparation_times") or [],
                       difficulty=h.get("difficulty"), price=h.get("price"),
                       nutrition=h.get("nutritions"))
            ings = []
            for g in d.get("recipe_groups") or []:
                for i in g.get("ingredients") or []:
                    ings.append({"group": g.get("headline"), "name": i.get("ingredient_name"),
                                 "quantity": i.get("amount"), "quantity_to": i.get("amountTo"),
                                 "unit": (i.get("unit") or {}).get("name"),
                                 "prefix": i.get("prefix"), "note": i.get("suffix")})
            rec["ingredients"] = ings
            rec["steps"] = [{"group": p.get("headline"), "text": (p.get("content") or "").strip()}
                            for p in d.get("preparation") or [] if (p.get("content") or "").strip()]
            rec["tips"] = [{"headline": t.get("headline"), "content": (t.get("content") or "").strip()}
                           for t in d.get("recipe_tips") or [] if (t.get("content") or "").strip()]
            return rec
        except json.JSONDecodeError:
            pass
    # --- fallback: XML attributes ---
    sv = head.find("d:CustomRecipeServing", NS)
    rec["servings"] = ({"amount": _num(sv.get("amount")), "unit": sv.get("plural")} if sv is not None else None)
    rec["times"] = [{"name": (e.get("name") or e.get("topic", "").rsplit("_", 1)[-1]).capitalize(),
                     "duration": int(_num(e.get("minutes")) or 0)} for e in head.findall("d:CustomRecipePreparation", NS)]
    n = {k: _num(_txt(head.find(f"d:CustomRecipeNutritionalValue{t}", NS)))
         for k, t in (("calories", "Calories"), ("kilojoule", "Kilojoule"), ("carbonhydrates", "Carbs"),
                      ("fat", "Fat"), ("protein", "Protein"))}
    rec["nutrition"] = n if any(v is not None for v in n.values()) else None
    ings, unresolved = [], 0
    for grp in head.findall("d:CustomRecipeIngredients", NS):
        hdr = _txt(grp.find("d:CustomRecipeIngredientsHeader", NS))
        for e in sorted(grp.findall("d:CustomRecipeIngredient", NS), key=lambda x: int(x.get("position") or 0)):
            name = e.get("plural") or topicmap.get(e.get("topic", ""))
            if not name:
                unresolved += 1
                continue
            unit = e.get("unit") or topicmap.get(e.get("unit_topic", ""))
            ings.append({"group": hdr, "name": name, "quantity": _num(e.get("amount")), "quantity_to": None,
                         "unit": None if unit in (None, "(Keine Einheit)") else unit,
                         "prefix": e.get("prefix"), "note": (e.get("suffix") or "").strip() or None})
    rec["ingredients"] = ings
    rec["names_resolved"] = unresolved == 0 and bool(ings)
    steps = []
    for g in head.findall("d:CustomRecipePreparationSteps", NS):
        c = g.find("d:CustomRecipePreparationsStepsContent", NS)
        if _txt(c):
            steps.append((int(c.get("position") or 0), {"group": None, "text": " ".join(c.text.split())}))
    rec["steps"] = [s for _, s in sorted(steps, key=lambda x: x[0])]
    tips = []
    for g in head.findall("d:CustomRecipeTipps", NS):
        c = g.find("d:CustomRecipeTippsContent", NS)
        if _txt(c):
            tips.append({"headline": None, "content": " ".join(c.text.split())})
    rec["tips"] = tips
    return rec


# ---------------------------------------------------------------- index / similarity
_STOP = {"mit", "und", "aus", "dem", "der", "die", "das", "von", "für", "auf", "ohne", "nach", "à", "la"}


def _toks(words: Iterable[str]) -> set[str]:
    out = set()
    for w in words:
        for t in re.findall(r"[a-zäöüß]+", (w or "").lower()):
            if len(t) > 3 and t not in _STOP:
                out.add(t[:6])
    return out


class ArchiveIndex:
    def __init__(self, records: list[dict]):
        self.records = records
        self._t = [(_toks([r.get("title") or ""]), _toks(i["name"] for i in r.get("ingredients", []) if i.get("name")))
                   for r in records]

    @classmethod
    def load_dir(cls, folder: str | Path, topicmap: dict[str, str] | None = None) -> "ArchiveIndex":
        recs = []
        for f in sorted(Path(folder).glob("*.xml")):
            r = parse_archive_xml(f, topicmap)
            if r and r.get("title"):
                recs.append(r)
        return cls(recs)

    def similar(self, title: str, ingredient_names: Iterable[str], k: int = 5) -> list[dict]:
        qt, qi = _toks([title]), _toks(ingredient_names)
        scored = []
        for r, (rt, ri) in zip(self.records, self._t):
            if not r.get("names_resolved") and not rt:
                continue
            jt = len(qt & rt) / len(qt | rt) if qt | rt else 0.0
            ji = len(qi & ri) / len(qi | ri) if qi | ri else 0.0
            s = 0.45 * jt + 0.55 * ji
            if s > 0:
                scored.append((s, jt, ji, r))
        scored.sort(key=lambda x: -x[0])
        return [{"id": r["id"], "title": r["title"], "modified": (r.get("modified") or "")[:10],
                 "similarity": round(s, 2), "title_overlap": round(jt, 2), "ingredient_overlap": round(ji, 2)}
                for s, jt, ji, r in scored[:k]]

    def titles_for_prompt(self, topic_words: Iterable[str], k: int = 12) -> list[str]:
        q = _toks(topic_words)
        hits = []
        for r, (rt, ri) in zip(self.records, self._t):
            if re.search(r"_txt|^[A-Z]{2,}\d|MFI-", r["title"] or ""):
                continue          # internal production names, not real titles
            s = len(q & (rt | ri))
            if s:
                hits.append((s, r["title"], (r.get("modified") or "")[:10]))
        hits.sort(key=lambda x: (-x[0], x[2]), reverse=False)
        return [f"{t} ({d})" for _, t, d in hits[:k]]


# ---------------------------------------------------------------- adapter to the flat recipe schema
_PREP = re.compile(r"vorbereit|zubereit|prep", re.I)
_COOK = re.compile(r"back|koch|gar|schmor|grill|brat", re.I)


def archive_to_flat(rec: dict) -> dict:
    """Convert a parsed archive record into the flat schema used by the renderer (see CONTRACTS.md)."""
    sv = rec.get("servings") or {}
    unit = sv.get("unit") if sv.get("unit") not in (None, "other") else None
    times = {"prep_min": None, "cook_min": None, "rest_min": None}
    for t in rec.get("times") or []:
        key = "prep_min" if _PREP.search(t.get("name") or "") else "cook_min" if _COOK.search(t.get("name") or "") else "rest_min"
        times[key] = (times[key] or 0) + int(t.get("duration") or 0)
    ingredients = []
    for n, i in enumerate(rec.get("ingredients") or [], 1):
        q = i.get("quantity")
        ingredients.append({"id": f"i{n}", "group": i.get("group"), "name": i.get("name"),
                            "quantity": q if q else None, "quantity_to": i.get("quantity_to") or None,
                            "unit": None if i.get("unit") in (None, "(Keine Einheit)") else i.get("unit"),
                            "prefix": i.get("prefix"), "note": (i.get("note") or "").strip() or None})
    flat = {
        "id": rec.get("id"), "title": rec.get("title"), "intro": None,
        "servings": {"amount": sv.get("amount") or 1, "unit": unit or "Portionen"},
        "times": times, "times_list": rec.get("times") or [],
        "ingredients": ingredients,
        "steps": [{"group": s.get("group"), "text": s["text"], "uses": [], "temperature_c": None, "duration_min": None}
                  for s in rec.get("steps") or []],
        "tips": rec.get("tips") or [], "serving_tip": None,
        "image_prompt": None, "image_alt": None,
        "archive_nutrition": rec.get("nutrition"),
        "source": {"kind": "archive", "id": rec.get("id"), "modified": rec.get("modified")},
    }
    return flat
