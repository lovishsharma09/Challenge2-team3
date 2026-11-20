"""Offline archive lookup on the local recipe export ZIP (never uploaded, never logged, never committed).

Source: recipe_export_5000_hackathon.zip = README.txt + auswahl_manifest.json + rezepte_export/*.xml
(namespace http://www.digicol.com/xmlns/dcx). Read directly from the ZIP, in memory. See docs/archive-profile.md.

What is used for similarity (all deterministic, no LLM, no network):
  - title (manifest `titel`, XML Headline/Title)        100% present
  - ingredient names (@prefix + @plural + @suffix)       94.5% of ingredients named; unnamed ones are UNKNOWN, not "absent"
  - main category (manifest `hauptkategorie`, derived from the title by the data provider)
What is deliberately NOT used: created/modified/DateImported/DateCreated. They are CMS/import timestamps; the README documents
no publication date, so every match reports "Publication date unavailable" and `last_published` stays None.
The export is a quota-based selection of 5,000 of 81,798 recipes (not representative): absence is never proof of a gap.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .llm import _env  # shared .env / environment reader

NS = {"d": "http://www.digicol.com/xmlns/dcx"}
MAX_XML_BYTES = 2_000_000
MAX_MATCHES = 3
SELECTION_NOTE = ("This export is a selection of 5,000 of 81,798 archive recipes, not a representative sample: "
                  "no match here does not mean the topic was never published, and counts are lower bounds.")
NOT_ASSESSED = "not_assessed"   # repetition risk needs a comparison with the SPECIFIC pitch; topic matches alone do not show it
DATE_NOTE = "Publication date unavailable (the export documents no publication date)."
UNNAMED_NOTE = "Ingredients without a readable name in the export are treated as unknown, not as absent."


@dataclass
class Recipe:
    id: str
    title: str
    category: str
    subtitle: str
    ingredients: list[tuple[int, str]]            # (position, normalized name)
    unnamed: int = 0


@dataclass
class Archive:
    recipes: list[Recipe] = field(default_factory=list)
    skipped: int = 0
    status: str = "ok"                             # "ok" | "unavailable"
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.status == "ok" and bool(self.recipes)


# ---------------------------------------------------------------- text normalisation
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).casefold().translate(_FOLD)).strip()


def stem(token: str) -> str:
    """Light German stemming, enough for Pastinake/Pastinaken, Linse/Linsen, Kürbis/Kürbisse."""
    for suffix in ("innen", "en", "er", "es", "e", "n", "s"):
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def query_terms(topic: str) -> list[str]:
    return [stem(t) for t in norm(topic).split() if len(t) >= 3]


def _hit(term: str, tokens: list[str]) -> str | None:
    """Return the matching token: same stem, or the term inside a German compound (Kuerbissuppe contains kuerbis)."""
    for tok in tokens:
        if stem(tok) == term or (len(term) >= 5 and term in tok):
            return tok
    return None


# ---------------------------------------------------------------- loading
def _parse_recipe(data: bytes, meta: dict) -> Recipe | None:
    if len(data) > MAX_XML_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return None                                # untrusted input: refuse DTD/entity tricks and oversize files
    try:
        head = ET.fromstring(data).find("d:head", NS)
    except ET.ParseError:
        return None
    if head is None:
        return None
    title = meta.get("titel") or (head.findtext("d:Headline", default="", namespaces=NS) or
                                  head.findtext("d:Title", default="", namespaces=NS))
    ingredients, unnamed = [], 0
    for ing in head.findall(".//d:CustomRecipeIngredient", NS):
        name = " ".join(p for p in (ing.get("prefix"), ing.get("plural"), ing.get("suffix")) if p).strip()
        try:
            pos = int(ing.get("position") or 999)
        except ValueError:
            pos = 999
        if ing.get("plural"):
            ingredients.append((pos, norm(name)))
        else:
            unnamed += 1
    return Recipe(id=str(meta.get("id", "")), title=str(title).strip(), category=str(meta.get("hauptkategorie") or ""),
                  subtitle=(head.findtext("d:SubHeadline", default="", namespaces=NS) or "").strip(),
                  ingredients=sorted(ingredients), unnamed=unnamed)


def load_archive(zip_path: str | Path | None) -> Archive:
    """Never raises: any problem becomes an `unavailable` archive with a reason."""
    if not zip_path:
        return Archive(status="unavailable", reason="no archive path configured (EDITOR_ARCHIVE_ZIP)")
    path = Path(zip_path).expanduser()
    if not path.is_file():
        return Archive(status="unavailable", reason="archive file not found")
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            manifest_name = next((n for n in names if n.endswith("auswahl_manifest.json")), None)
            if manifest_name is None:
                return Archive(status="unavailable", reason="manifest auswahl_manifest.json missing in the archive")
            manifest = json.loads(zf.read(manifest_name).decode("utf-8"))
            entries = manifest.get("rezepte") if isinstance(manifest, dict) else None
            if not isinstance(entries, list):
                return Archive(status="unavailable", reason="manifest has an unexpected structure (no 'rezepte' list)")
            prefix = manifest_name[: -len("auswahl_manifest.json")]
            archive = Archive()
            for meta in entries:
                datei = meta.get("datei") if isinstance(meta, dict) else None
                if not isinstance(datei, str):             # entry has the wrong shape: skip, never crash
                    archive.skipped += 1
                    continue
                member = prefix + datei
                if member not in names or not member.endswith(".xml") or ".." in member:
                    archive.skipped += 1
                    continue
                recipe = _parse_recipe(zf.read(member), {k: (v if isinstance(v, str) else "") for k, v in meta.items()
                                                         if k in ("id", "titel", "hauptkategorie")} | {"id": str(meta.get("id", ""))})
                if recipe is None or not recipe.title:
                    archive.skipped += 1
                    continue
                archive.recipes.append(recipe)
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        return Archive(status="unavailable", reason=f"archive could not be read ({type(exc).__name__})")
    if not archive.recipes:
        return Archive(status="unavailable", reason="archive contains no readable recipes")
    return archive


_cache: dict[str, Archive] = {}


def configured_archive() -> Archive:
    """Archive from EDITOR_ARCHIVE_ZIP (environment or the git-ignored .env). Parsed once per process."""
    path = _env("EDITOR_ARCHIVE_ZIP")
    if path not in _cache:
        _cache[path] = load_archive(path)
    return _cache[path]


# ---------------------------------------------------------------- lookup
def _score(recipe: Recipe, terms: list[str]) -> tuple[int, list[str]]:
    """Returns (score, explanations). ALL query terms must be covered (a topic like 'Ofen-Feta' needs both words, or the
    compound 'Ofenfeta' in the title). Credible = at least one title hit, subtitle hit or main-ingredient hit (position <= 3)."""
    title_tokens, sub_tokens = norm(recipe.title).split(), norm(recipe.subtitle).split()
    score, why, covered, strong = 0, [], 0, False
    for term in terms:
        if (tok := _hit(term, title_tokens)):
            score, strong, covered = score + 10, True, covered + 1
            why.append(f"title contains '{tok}'")
        elif (tok := _hit(term, sub_tokens)):
            score, strong, covered = score + 4, True, covered + 1
            why.append(f"subtitle contains '{tok}'")
        else:
            for pos, name in recipe.ingredients:
                tok = _hit(term, name.split())
                if tok:
                    covered += 1
                    if pos <= 3:
                        score, strong = score + 3, True
                        why.append(f"main ingredient (position {pos}): '{tok}'")
                    else:
                        score += 1
                        why.append(f"ingredient '{tok}'")
                    break
    if len(terms) > 1 and covered < len(terms):          # compound spelling: 'ofenfeta' for 'ofen' + 'feta'
        joined = "".join(terms)
        if any(joined in tok for tok in title_tokens):
            return 12, [f"title contains the compound '{joined}'"]
        return 0, []
    return (score if strong and covered == len(terms) else 0), why


def lookup(archive: Archive, topic: str) -> dict:
    """Archive block for the proposal contract (superset of Person A's handoff schema)."""
    base = {"source": "export", "last_published": None,
            "assumption": SELECTION_NOTE + " " + UNNAMED_NOTE + " Matches show prior coverage of the topic, not that a specific pitch repeats an existing recipe, so repetition risk is not assessed here."}
    if not archive.available:
        return {**base, "status": "unavailable", "available": False, "match_status": "archive_unavailable",
                "similar_recipes": [], "repetition_risk": NOT_ASSESSED, "content_gap": "",
                "assumption": f"Archive not available: {archive.reason or 'unknown reason'}."} | {"repetition_risk": NOT_ASSESSED}
    terms = query_terms(topic)
    scored = []
    if terms:
        for r in archive.recipes:
            s, why = _score(r, terms)
            if s:
                scored.append((-s, norm(r.title), r.id, r, why))
    scored.sort(key=lambda t: t[:3])               # deterministic: score, then title, then id
    n = len(scored)
    similar = [{"id": r.id, "title": r.title, "category": r.category, "why": "; ".join(dict.fromkeys(why)),
                "publication_date": None, "publication_note": DATE_NOTE} for (_s, _t, _i, r, why) in scored[:MAX_MATCHES]]
    cats = Counter(r.category for (_s, _t, _i, r, _w) in scored if r.category)
    if n == 0:
        gap = (f"Hypothesis: no credible match for '{topic}' in this export; it may be a gap, but the export is only a "
               "selection, so check the full archive before treating it as one.")
    else:
        shown = cats.most_common(4)
        more = f" (top {len(shown)} of {len(cats)} shown)" if len(cats) > len(shown) else ""
        gap = (f"Coverage in this export, not a gap analysis: {n} credible match(es) for the topic in {len(cats)} "
               f"categor{'y' if len(cats) == 1 else 'ies'}{more}: " + ", ".join(f"{c} ({k})" for c, k in shown) + ".")
    return {**base, "status": "ok", "available": True,
            "match_status": "matches_found" if n else "no_match_found", "similar_recipes": similar,
            "match_count": n, "repetition_risk": NOT_ASSESSED, "content_gap": gap}
