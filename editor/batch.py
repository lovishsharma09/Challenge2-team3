"""Load a saved Person A proposal batch (local JSON) for the editor desk. No re-scoring, no imports of A's code.

Field names are Person A's (schemas/proposals.schema.json on origin/main): proposals[] with id, title, topic, rank, rank_score,
trend{score, points, why_relevant, sources, wikimedia?}, brand_fit{reasoning, ...}, archive{status, available, match_status,
similar_recipes, repetition_risk, content_gap, assumption}, recipe_ideas[], and rejected_topics[] with id, topic, reason.
Unknown extra fields are kept untouched (original labels stay separate from the editor desk's English presentation copy).

Stricter than the schema where the plan requires it: exactly five selectable proposals, unique ids, unique positive integer ranks,
a non-empty recipe angle and brand-fit reasoning, traceable trend sources, and an archive block that is internally consistent.
A missing or invalid batch raises BatchError with readable messages; nothing is replaced by mock data.
Local only: a batch may contain archive titles, so it must stay out of git (data/local/ is git-ignored).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_BYTES = 5_000_000
MAX_TEXT = 3000
MAX_SIMILAR = 50
MAX_POINTS = 400
MATCH_STATUS = {"matches_found", "no_match_found", "archive_unavailable"}
RISK = {"low", "medium", "high", "unknown"}
WIKI_STATUS = {"available", "no_article_found", "no_data", "unavailable"}
REQUIRED = ("id", "title", "topic", "trend", "brand_fit", "archive", "recipe_ideas", "rank_score", "rank")
# Phrases of the placeholder recipe ideas seen in the first version of A's pipeline: flag them, they are not concrete angles.
TEMPLATE_ANGLES = (re.compile(r"^Einfache .+-Variante in einem 30-Minuten-Format$"),
                   re.compile(r"^Saisonale .+-Version zum Vorbereiten$"),
                   re.compile(r"^Klassische .+-Version mit klarer Wochenendoption$"))


def is_template_angle(text) -> bool:
    """True for the placeholder recipe ideas ('Einfache X-Variante in einem 30-Minuten-Format' and its siblings)."""
    return isinstance(text, str) and any(t.match(text.strip()) for t in TEMPLATE_ANGLES)


class BatchError(ValueError):
    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("; ".join(messages))


@dataclass
class Batch:
    proposals: list[dict]                  # sorted by A's rank; original dicts, untouched
    rejected: list[dict]
    source_label: str
    path: str
    sha256: str
    warnings: list[str] = field(default_factory=list)
    draft_label: str = ""          # set for a team draft: shown instead of "Person A saved batch"
    draft_status: str = ""
    based_on: str = ""


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _one_of(value, allowed) -> bool:
    """Type first, then membership: a list/dict in the JSON must be a validation error, never a TypeError."""
    return isinstance(value, str) and value in allowed


def _text(value, where: str, errors: list[str], *, required=True) -> bool:
    if not isinstance(value, str) or (required and not value.strip()):
        errors.append(f"{where} must be a non-empty text")
        return False
    if len(value) > MAX_TEXT:
        errors.append(f"{where} is too long ({len(value)} characters, limit {MAX_TEXT})")
        return False
    return True


def _check_proposal(p, idx: int, errors: list[str], warnings: list[str], templated: list[int]):
    name = f"proposal #{idx + 1}"
    if not isinstance(p, dict):
        errors.append(f"{name} must be an object")
        return
    name = f"proposal #{idx + 1} (id {p.get('id')!r})"
    for key in REQUIRED:
        if key not in p:
            errors.append(f"{name}: missing field '{key}'")
    for key in ("id", "title", "topic"):
        if key in p:
            _text(p[key], f"{name}: '{key}'", errors)
    if "rank" in p and not (isinstance(p["rank"], int) and not isinstance(p["rank"], bool) and p["rank"] >= 1):
        errors.append(f"{name}: 'rank' must be an integer >= 1")
    if "rank_score" in p and not _is_num(p["rank_score"]):
        errors.append(f"{name}: 'rank_score' must be a number")

    trend = p.get("trend")
    if "trend" in p:
        if not isinstance(trend, dict):
            errors.append(f"{name}: 'trend' must be an object")
        else:
            if not _is_num(trend.get("score")):
                errors.append(f"{name}: trend.score must be a number")
            _text(trend.get("why_relevant"), f"{name}: trend.why_relevant", errors)
            src = trend.get("sources")
            if not isinstance(src, list) or not src or not all(isinstance(s, str) and s.strip() for s in src):
                errors.append(f"{name}: trend.sources must list at least one source (traceable evidence)")
            pts = trend.get("points")
            if not isinstance(pts, list) or len(pts) > MAX_POINTS or not all(
                    isinstance(x, dict) and {"date", "value", "source"} <= set(x) for x in pts):
                errors.append(f"{name}: trend.points must be a list of {{date, value, source}} (max {MAX_POINTS})")
            wiki = trend.get("wikimedia")
            if wiki is not None and (not isinstance(wiki, dict) or not _one_of(wiki.get("status"), WIKI_STATUS)):
                errors.append(f"{name}: trend.wikimedia.status must be one of {sorted(WIKI_STATUS)}")

    brand = p.get("brand_fit")
    if "brand_fit" in p:
        if not isinstance(brand, dict):
            errors.append(f"{name}: 'brand_fit' must be an object")
        else:
            _text(brand.get("reasoning"), f"{name}: brand_fit.reasoning", errors)
            if brand.get("score") is not None and not _is_num(brand.get("score")):
                errors.append(f"{name}: brand_fit.score must be a number or null")

    arc = p.get("archive")
    if "archive" in p:
        if not isinstance(arc, dict):
            errors.append(f"{name}: 'archive' must be an object")
        else:
            for key in ("status", "available", "match_status", "similar_recipes", "repetition_risk", "content_gap", "assumption"):
                if key not in arc:
                    errors.append(f"{name}: archive.{key} is missing")
            sim = arc.get("similar_recipes")
            status = arc.get("match_status")
            if not _one_of(status, MATCH_STATUS):
                errors.append(f"{name}: archive.match_status must be one of {sorted(MATCH_STATUS)}")
            if not _one_of(arc.get("repetition_risk"), RISK):
                errors.append(f"{name}: archive.repetition_risk must be one of {sorted(RISK)}")
            if not isinstance(arc.get("available"), bool):
                errors.append(f"{name}: archive.available must be true or false")
            if not isinstance(sim, list) or len(sim) > MAX_SIMILAR or not all(
                    isinstance(r, dict) and isinstance(r.get("title"), str) and r["title"].strip() for r in sim):
                errors.append(f"{name}: archive.similar_recipes must be a list of recipes with a title (max {MAX_SIMILAR})")
            elif status == "matches_found" and not sim:
                errors.append(f"{name}: archive says matches_found but lists no recipe (not traceable)")
            elif status == "no_match_found" and (sim or arc.get("available") is not True):
                errors.append(f"{name}: archive says no_match_found but is inconsistent (recipes listed or not available)")
            elif status == "archive_unavailable" and (sim or arc.get("available") is not False):
                errors.append(f"{name}: archive says archive_unavailable but is inconsistent (recipes listed or available=true)")

    ideas = p.get("recipe_ideas")
    if "recipe_ideas" in p:
        if not isinstance(ideas, list) or not ideas or not all(isinstance(i, str) and i.strip() for i in ideas):
            errors.append(f"{name}: recipe_ideas needs at least one concrete recipe angle (non-empty text)")
        elif any(len(i) > MAX_TEXT for i in ideas):
            errors.append(f"{name}: a recipe idea is too long")
        elif any(is_template_angle(i) for i in ideas):
            templated.append(idx + 1)


def validate_batch(data) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["the batch must be a JSON object with 'proposals' and 'rejected_topics'"], warnings
    props, rejected = data.get("proposals"), data.get("rejected_topics")
    if not isinstance(props, list):
        return ["'proposals' must be a list"], warnings
    if not isinstance(rejected, list):
        errors.append("'rejected_topics' must be a list (it may be empty)")
    if len(props) != 5:
        errors.append(f"the batch must contain exactly 5 proposals, found {len(props)}")
    templated: list[int] = []
    for i, p in enumerate(props):
        _check_proposal(p, i, errors, warnings, templated)
    if templated:                                      # one grouped message instead of one box per proposal
        which = ", ".join(f"#{n}" for n in templated)
        warnings.append(f"{len(templated)} of {len(props)} recipe angles look like templates, not concrete angles (proposals {which}). "
                        "Ask Person A for specific angles before judging the pitches.")
    ids = [p.get("id") for p in props if isinstance(p, dict) and isinstance(p.get("id"), str)]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"duplicate proposal id {dup!r}")
    ranks = [p.get("rank") for p in props if isinstance(p, dict) and isinstance(p.get("rank"), int) and not isinstance(p.get("rank"), bool)]
    for dup in sorted({r for r in ranks if ranks.count(r) > 1}):
        errors.append(f"duplicate rank {dup}: the order is ambiguous")
    if isinstance(rejected, list):
        for i, r in enumerate(rejected):
            if not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r[k].strip() for k in ("id", "topic", "reason")):
                errors.append(f"rejected_topics #{i + 1} must be an object with id, topic and reason")
    if not errors:
        if sorted(ranks) != list(range(1, 6)):
            warnings.append(f"ranks are {sorted(ranks)} instead of 1-5; shown in the supplied rank order")
        if ranks != sorted(ranks):
            warnings.append("the order of the file differs from the ranks; shown in rank order")
    return errors, warnings


def _team_draft(source) -> dict | None:
    """Top-level 'source' block of a team draft: {"kind": "team_draft", "label", "status", "based_on": {"file", "sha256"}}.
    Anything else (missing, wrong shape, other kind) is an ordinary saved batch."""
    if not isinstance(source, dict) or source.get("kind") != "team_draft":
        return None
    def clean(x, default, limit=200):
        return " ".join(x.split())[:limit] if isinstance(x, str) and x.strip() else default
    based = source.get("based_on") if isinstance(source.get("based_on"), dict) else {}
    based_on = clean(based.get("file"), "")
    if based_on and isinstance(based.get("sha256"), str):
        based_on += f" (sha256 {based['sha256'][:12]})"
    return {"label": clean(source.get("label"), "Team draft for review"), "status": clean(source.get("status"), "Not approved"),
            "based_on": based_on}


def load_batch(path) -> Batch:
    """Raises BatchError (readable messages) for a missing, oversized, malformed or invalid batch."""
    if not path or not str(path).strip():
        raise BatchError(["no batch file configured (set EDITOR_PROPOSALS_JSON or enter a path)"])
    p = Path(str(path)).expanduser()
    if not p.is_file():
        raise BatchError([f"batch file not found: {p.name}"])
    if p.stat().st_size > MAX_BYTES:
        raise BatchError([f"batch file is too large ({p.stat().st_size} bytes, limit {MAX_BYTES})"])
    raw = p.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise BatchError(["batch file is not valid UTF-8 text"]) from None
    except (json.JSONDecodeError, RecursionError) as exc:
        raise BatchError([f"batch file is not valid JSON ({type(exc).__name__}: {getattr(exc, 'msg', 'too deeply nested')})"]) from None
    try:
        errors, warnings = validate_batch(data)
    except Exception as exc:  # noqa: BLE001 - last resort: an unexpected shape must never crash the screen
        raise BatchError([f"the batch has an unexpected structure ({type(exc).__name__})"]) from None
    if errors:
        raise BatchError(errors)
    digest = hashlib.sha256(raw).hexdigest()
    proposals = sorted(copy.deepcopy(data["proposals"]), key=lambda x: x["rank"])
    saved = f"file {p.name} · sha256 {digest[:12]} · saved {datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}"
    draft = _team_draft(data.get("source"))
    if draft:                                          # a draft must never be presented as Person A's approved batch
        label = f"{draft['label']} · {draft['status']} · {saved} · {len(proposals)} pitches in the supplied order"
        return Batch(proposals, copy.deepcopy(data["rejected_topics"]), label, str(p), digest, warnings,
                     draft["label"], draft["status"], draft["based_on"])
    label = f"Person A saved batch · {saved} · {len(proposals)} pitches in A's order"
    return Batch(proposals, copy.deepcopy(data["rejected_topics"]), label, str(p), digest, warnings)


def propose_from_batch(batch: Batch):
    """A fixed `propose` for the workflow: returns the supplied pitches as they are (no re-scoring, no re-ranking).
    It cannot supply replacements, so the workflow disables 'Reject all' for it (supports_rerun is False)."""
    def propose_fixed(exclude: set[str], limit: int = 5):
        if exclude:
            return [], []
        return copy.deepcopy(batch.proposals), copy.deepcopy(batch.rejected)
    propose_fixed.supports_rerun = False
    propose_fixed.source_label = batch.source_label
    return propose_fixed


def summarize(batch: Batch) -> str:
    """Compact, human-readable check of a loaded batch (what the editor desk will show), for the file's author."""
    lines = [batch.source_label]
    for p in batch.proposals:
        a, ideas = p["archive"], p["recipe_ideas"]
        lines.append(f"#{p['rank']} {p['id']} | topic {p['topic']!r} | angle: {ideas[0][:90]!r} | brand reason: {len(p['brand_fit']['reasoning'])} chars"
                     f" | archive: {a['match_status']} ({len(a['similar_recipes'])} listed) | trend sources: {len(p['trend']['sources'])}")
    lines += [f"WARNING: {w}" for w in batch.warnings]
    lines.append(f"rejected topics: {len(batch.rejected)}")
    return "\n".join(lines)


if __name__ == "__main__":      # python -m editor.batch path/to/batch.json  -> validate before sending it to Person B
    import sys
    try:
        print(summarize(load_batch(sys.argv[1] if len(sys.argv) > 1 else "")))
    except BatchError as exc:
        print("INVALID BATCH:")
        print("\n".join(f"- {m}" for m in exc.messages))
        sys.exit(1)
