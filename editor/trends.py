"""Trend candidates from the PROVIDED data only (offline, no API calls, no LLM).

Inputs (data/trends/ of the repo, or EDITOR_TRENDS_DIR):
  google-trends/*.csv                      Top/Rising Searches, queries and topics, DE, 2026-10-18..2026-11-18
  wikimedia/Wikimedia_Pageviews_Fallback_*.xlsx   snapshot 2026-11-18: Google term -> German Wikipedia article, 7-day views,
                                           change %, mapping method, review flag; plus 14 daily values per article
Rows are grouped by the mapped Wikipedia article (so 'rosenkohl rezept' and 'rosenkohl rezepte' become one topic).

Score (0-100, heuristic, shown to the editor with all components):
  G = max over RISING rows of  100*log10(1+increase_pct)/log10(1+1500) * fg,  fg = min(1, (interest_index+5)/25)
      increase and interest index always come from the SAME row (never mixed across rows of a group)
  W = 100*log10(1+wiki_change_pct)/log10(1+500) * fw,  fw = min(1, latest_7d_views/200)    (real page views)
  score = 0.5*G + 0.5*W   (Wikipedia not contributing: 0.5*G and flagged "single source")
The Google "search interest" is a relative 0-100 INDEX inside the supplied export, not an absolute search volume. Most recipe
queries have an index of 0-1, so their huge 'increase %' values come from a tiny base and are damped by fg.
Wikipedia evidence states (kept distinct): available | unavailable (workbook missing/unreadable) | no_article_found (no mapping row,
or mapping flagged for review) | no_data (mapped, but no usable views). The snapshot is credited as a source only when available.

Eligible for a proposal: a group with a recipe-intent query ('rezept'/'recipe') AND at least one RISING row.
Everything else gets a credible "no" with a data-based reason (declining, no rising signal, topic-only, family cap, ...).
"""
from __future__ import annotations

import csv
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

SNAPSHOT_LABEL = "Wikimedia fallback snapshot 2026-11-18 (7 days 2026-11-04..10 vs 2026-11-11..17)"
MAX_BYTES = 5_000_000
FAMILY_CAP = 2
# Editorial families used only to avoid five near-identical proposals (keyword -> family). Editable on purpose.
FAMILIES = {
    "Weihnachtsgebäck": ("plätzchen", "kekse", "keks", "kipferl", "spitzbuben", "makronen", "spritzgebäck", "zimtstern",
                         "engelsaugen", "lebkuchen", "stollen", "husarenkrapferl", "linzer", "weihnachts", "nussecken",
                         "ausstech", "gebrannte", "weckmann", "cookie", "biscuit", "gingerbread", "gebäck", "mandel"),
    "Kohl": ("kohl", "wirsing", "kale", "cabbage", "sprout"),
    "Suppe": ("suppe", "eintopf", "soup"),
}
# Generic, brand and appliance terms that are never a recipe topic (editorial stoplist, kept out of proposals AND the "no" list).
NON_DISH = ("chefkoch", "thermomix", "airfryer", "air fryer", "fritteuse", "kochrezept", "rezepte", "ndr", "hier und heute",
            "schnelle", "veganism", "vegetarianism", "ernährung", "oven", "backofen", "dessert", "sauce", "baking", "backen")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


# ---------------------------------------------------------------- parsing
def parse_pct(text) -> int | None:
    """'1.450 %' -> 1450, '-30 %' -> -30, '' / 'Breakout' -> None (German thousands separator)."""
    m = re.fullmatch(r"\s*([+-]?[\d.]+)\s*%?\s*", str(text or ""))
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except ValueError:
        return None


def parse_int(text) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_csv_rows(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_BYTES:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_xlsx(path: Path) -> dict[str, list[dict[str, str | None]]]:
    """Minimal stdlib reader: {sheet name: [ {column letter: text} per row ]}. Never executes anything."""
    out: dict[str, list[dict]] = {}
    with zipfile.ZipFile(path) as zf:
        if sum(i.file_size for i in zf.infolist()) > 50 * MAX_BYTES:
            raise ValueError("workbook too large")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = ["".join(t.text or "" for t in si.iter(M + "t"))
                      for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall(M + "si")]
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(zf.read("xl/workbook.xml")).find(M + "sheets"):
            target = rels.get(sheet.get(R + "id"), "")
            member = "xl/" + target.lstrip("/").removeprefix("xl/")
            rows = []
            for row in ET.fromstring(zf.read(member)).iter(M + "row"):
                cells = {}
                for c in row.findall(M + "c"):
                    v = c.find(M + "v")
                    col = re.match(r"[A-Z]+", c.get("r", "")).group(0)
                    cells[col] = None if v is None else (shared[int(v.text)] if c.get("t") == "s" else v.text)
                rows.append(cells)
            out[sheet.get("name")] = rows
    return out


# ---------------------------------------------------------------- data model
@dataclass
class Signal:
    signal: str                 # "rising" | "top"
    kind: str                   # "query" | "topic"
    term: str
    interest: int | None
    increase: int | None        # percent, may be negative


@dataclass
class WikiRow:
    article: str
    views_prev: int | None
    views_latest: int | None
    change_pct: float | None    # percent (xlsx stores a fraction)
    status: str
    mapping: str
    review: bool


@dataclass
class Group:
    key: str
    topic: str
    signals: list[Signal] = field(default_factory=list)
    wiki: WikiRow | None = None
    points: list[dict] = field(default_factory=list)
    wiki_reason: str = ""          # why no Wikipedia evidence: no_mapping | review_flagged | no_data | source_missing | source_unreadable
    terms_without_wiki: int = 0


@dataclass
class TrendData:
    groups: list[Group]
    notes: list[str]
    wiki_state: str = "ok"         # ok | missing | unreadable


def _kind(file_name: str) -> tuple[str, str] | None:
    m = re.match(r"searched_with_(rising|top)-searches_(queries|topics)_", file_name)
    return (m.group(1), "query" if m.group(2) == "queries" else "topic") if m else None


def clean_term(term: str) -> str:
    return " ".join(w for w in re.sub(r"\(.*?\)", " ", str(term)).split() if w.casefold() not in ("rezept", "rezepte", "recipe"))


def load_trends(base: str | Path) -> TrendData:
    """Raises FileNotFoundError/ValueError for missing or malformed inputs; callers show a clear message."""
    base = Path(base)
    csvs = sorted((base / "google-trends").glob("searched_with_*.csv"))
    if not csvs:
        raise FileNotFoundError("no Google Trends CSV files found")
    signals: list[Signal] = []
    for path in csvs:
        kind = _kind(path.name)
        if not kind:
            continue
        first = "query" if kind[1] == "query" else "topic"
        for row in read_csv_rows(path):
            term = (row.get(first) or "").strip()
            if term:
                signals.append(Signal(kind[0], kind[1], term, parse_int(row.get("search interest")),
                                      parse_pct(row.get("increase percent"))))
    if not signals:
        raise ValueError("Google Trends files contain no rows")
    notes = [f"{len(signals)} Google Trends rows read (DE, 2026-10-18 to 2026-11-18)"]

    wiki_state = "ok"
    wiki: dict[tuple, WikiRow] = {}
    daily: dict[str, list[dict]] = {}
    xlsx = next(iter(sorted((base / "wikimedia").glob("*.xlsx"))), None)
    if xlsx is None:
        wiki_state = "missing"
        notes.append("Wikimedia snapshot not found: Wikipedia evidence unavailable")
    else:
        try:
            sheets = read_xlsx(xlsx)
        except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError, OSError, AttributeError) as exc:
            sheets, wiki_state = {}, "unreadable"
            notes.append(f"Wikimedia snapshot unreadable ({type(exc).__name__}): Wikipedia evidence unavailable")
        for r in sheets.get("Topic summary", [])[1:]:
            term = r.get("C")
            if not term:
                continue
            frac = None
            try:
                frac = float(r.get("O")) * 100 if r.get("O") is not None else None
            except ValueError:
                frac = None
            wiki[(r.get("A"), r.get("B"), term)] = WikiRow(
                article=r.get("F") or "", views_prev=parse_int(r.get("K")), views_latest=parse_int(r.get("N")),
                change_pct=frac, status=r.get("P") or "", mapping=r.get("G") or "", review=(r.get("H") == "1"))
        for r in sheets.get("Daily pageviews", [])[1:]:
            if r.get("D") == "ok" and parse_int(r.get("C")) is not None and r.get("A"):
                daily.setdefault(r["A"], []).append({"date": (r.get("B") or "")[:10], "value": int(r["C"]),
                                                     "source": "Wikimedia snapshot"})
        if sheets:
            notes.append(SNAPSHOT_LABEL)

    groups: dict[str, Group] = {}
    for s in signals:
        w = wiki.get((s.signal, s.kind, s.term))
        if wiki_state != "ok":
            reason = "source_missing" if wiki_state == "missing" else "source_unreadable"
        elif w is None or not w.article:
            reason = "no_mapping"
        elif w.review:
            reason = "review_flagged"
        elif w.status != "ok" or w.change_pct is None:
            reason = "no_data"
        else:
            reason = ""
        usable = reason == ""
        key = ("a:" + w.article.casefold()) if usable else ("t:" + clean_term(s.term).casefold())
        g = groups.setdefault(key, Group(key=key, topic=(w.article.replace("_", " ") if usable else clean_term(s.term).strip().title())))
        g.signals.append(s)
        if usable and g.wiki is None:
            g.wiki, g.points, g.wiki_reason = w, daily.get(w.article, []), ""
        elif not usable and g.wiki is None and not g.wiki_reason:
            g.wiki_reason = reason
        elif not usable:
            g.terms_without_wiki += 1
    return TrendData(list(groups.values()), notes, wiki_state)


# ---------------------------------------------------------------- scoring + selection
def _recipe_intent(g: Group) -> bool:
    return any(s.kind == "query" and re.search(r"\b(rezept|rezepte|recipe)\b", s.term.casefold()) for s in g.signals)


def best_google_row(g: Group) -> tuple[Signal | None, float, float]:
    """The rising row with the highest damped growth score. Growth and interest index come from the SAME row."""
    best, best_g, best_f = None, 0.0, 0.0
    for sg in sorted(g.signals, key=lambda x: x.term):
        if sg.signal != "rising" or sg.increase is None or sg.increase <= 0:
            continue
        factor = min(1.0, ((sg.interest or 0) + 5) / 25)
        value = 100 * math.log10(1 + sg.increase) / math.log10(1 + 1500) * factor
        if value > best_g:
            best, best_g, best_f = sg, value, factor
    return best, min(best_g, 100.0), best_f


def score_group(g: Group) -> dict:
    row, G, fg = best_google_row(g)
    w_ok = g.wiki is not None and g.wiki.change_pct is not None
    W = fw = None
    if w_ok:
        fw = min(1.0, (g.wiki.views_latest or 0) / 200)
        W = min(100.0, 100 * math.log10(1 + max(g.wiki.change_pct, 0)) / math.log10(1 + 500) * fw)
    score = 0.5 * G + 0.5 * W if w_ok else 0.5 * G
    return {"score": round(min(score, 100), 1), "google": round(G, 1), "wikipedia": None if W is None else round(W, 1),
            "best_term": row.term if row else None, "rising_increase_pct": row.increase if row else 0,
            "search_interest_index": (row.interest or 0) if row else 0, "interest_factor_google": round(fg, 2),
            "views_factor_wikipedia": None if fw is None else round(fw, 2), "single_source": not w_ok}


def is_non_dish(g: Group) -> bool:
    names = [g.topic.casefold()] + [clean_term(t.term).casefold() for t in g.signals[:1]]
    return any(n.strip() in NON_DISH or n.strip() == "" for n in names) or g.topic.casefold() in NON_DISH


def family_of(g: Group) -> str | None:
    text = " ".join([g.topic] + [s.term for s in g.signals]).casefold()
    return next((fam for fam, words in FAMILIES.items() if any(w in text for w in words)), None)


def select(data: TrendData, limit: int = 5, exclude: set[str] | None = None):
    """Returns (accepted: [(Group, components)], rejected: [{topic, reason}]) with data-based reasons."""
    exclude = {e.casefold() for e in (exclude or set())}
    accepted, rejected, per_family = [], [], {}
    ranked = []
    for g in data.groups:
        if g.topic.casefold() in exclude or is_non_dish(g):
            continue
        has_rising = any(s.signal == "rising" and (s.increase or 0) > 0 for s in g.signals)
        if not _recipe_intent(g):
            rejected.append((0.5, g.topic, "Topic-only signal: no recipe-intent search query (rezept/recipe) for it, so it is not a recipe idea."))
        elif not has_rising:
            neg = [s for s in g.signals if (s.increase or 0) < 0]
            if neg:
                worst = min(neg, key=lambda s: s.increase)
                rejected.append((1 + (max(s.interest or 0 for s in g.signals) / 100), g.topic,
                                 f"Declining: '{worst.term}' {worst.increase:+d}% in the Google Trends period."))
            else:
                rejected.append((0.2, g.topic, "No rising signal: stable or flat search interest."))
        else:
            ranked.append((score_group(g), g))
    ranked.sort(key=lambda t: (-t[0]["score"], t[1].topic.casefold()))
    for comp, g in ranked:
        fam = family_of(g)
        if len(accepted) >= limit:
            rejected.append((2 + comp["score"] / 100, g.topic, f"Ranked below the top {limit} (score {comp['score']})."))
        elif fam and per_family.get(fam, 0) >= FAMILY_CAP:
            rejected.append((2 + comp["score"] / 100, g.topic, f"Family cap: already {FAMILY_CAP} proposals in '{fam}' (score {comp['score']})."))
        else:
            accepted.append((g, comp))
            per_family[fam] = per_family.get(fam, 0) + 1
    rejected.sort(key=lambda t: (-t[0], t[1].casefold()))
    close = [r for r in rejected if r[0] >= 2][:5]            # near misses first, then real declines / non-ideas
    other = [r for r in rejected if r[0] < 2][:4]
    return accepted, [{"topic": t, "reason": r} for _s, t, r in close + other]


# ---------------------------------------------------------------- proposal blocks
WIKI_REASONS = {
    "source_missing": ("unavailable", "Wikimedia snapshot file not found"),
    "source_unreadable": ("unavailable", "Wikimedia snapshot could not be read"),
    "no_mapping": ("no_article_found", "no Wikipedia article is mapped to this Google term in the snapshot"),
    "review_flagged": ("no_article_found", "the article mapping is flagged for review (search_result_review), so it is not used"),
    "no_data": ("no_data", "an article is mapped but the snapshot has no usable page views for it"),
}


def trend_block(g: Group, comp: dict) -> dict:
    rising = sorted((s for s in g.signals if s.signal == "rising" and (s.increase or 0) > 0), key=lambda s: (-(s.increase or 0), s.term))
    best = next((s for s in rising if s.term == comp["best_term"]), rising[0])
    parts = [f"Google Trends rising: '{best.term}' {best.increase:+d}% (search-interest index {best.interest if best.interest is not None else 'n/a'}/100)"]
    if len(rising) > 1:
        parts.append(f"+{len(rising) - 1} more rising term(s)")
    w = g.wiki
    if w and w.change_pct is not None:
        parts.append(f"Wikipedia '{w.article}' 7-day views {w.views_prev}→{w.views_latest} ({w.change_pct:+.0f}%)")
    caveats = []
    if comp["interest_factor_google"] < 0.5:
        caveats.append("the search-interest index of the strongest row is very low (a relative index, not a volume), so its increase % comes from a tiny base and is unreliable")
    if comp["single_source"]:
        caveats.append("single source: no Wikipedia evidence")
    why = "; ".join(parts) + "." + (" Caveat: " + "; ".join(caveats) + "." if caveats else "")
    sources = ["Google Trends supplied CSV (DE, 2026-10-18..2026-11-18)"]
    if w and w.change_pct is not None:
        wiki = {"status": "available", "article": w.article, "score": comp["wikipedia"], "points": g.points, "error": None,
                "views_previous_7d": w.views_prev, "views_latest_7d": w.views_latest, "change_pct": round(w.change_pct, 1),
                "mapping_method": w.mapping, "method": SNAPSHOT_LABEL, "reason": ""}
        sources.append(SNAPSHOT_LABEL)                       # credited only because it contributed evidence
    else:
        status, reason = WIKI_REASONS.get(g.wiki_reason, ("no_article_found", "no usable Wikipedia evidence"))
        wiki = {"status": status, "article": None, "score": None, "points": [], "reason": reason,
                "error": reason if status == "unavailable" else None, "method": None}
    return {"score": comp["score"], "why_relevant": why, "components": comp, "wikimedia": wiki, "sources": sources,
            "google_terms": [{"term": s.term, "kind": s.kind, "signal": s.signal, "search_interest_index": s.interest,
                              "increase_pct": s.increase} for s in g.signals][:8],
            "sparkline": [p["value"] for p in g.points]}
