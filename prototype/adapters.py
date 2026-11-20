"""Glue between the three parts, without changing their contracts.

Person A  src/challenge2  -> proposals.json      (schemas/proposals.schema.json)
Person B  editor/         -> audit log + selection.json (person_c/docs/CONTRACTS.md: picks, selected_ids, steering_notes, …)
Person C  person_c/       -> recipes.json, review.json, nutrition.json, cards/*.html, stage_c_log.json

Every live run lives in prototype/runs/<timestamp>/ (git-ignored) and can be replayed; prototype/demo_cache/ is one
committed run (no keys, relative paths) for demos without network.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSON_C = ROOT / "person_c"
for p in (str(ROOT), str(PERSON_C / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

RUNS_DIR = ROOT / "prototype" / "runs"
DEMO_DIR = ROOT / "prototype" / "demo_cache"
SCHEMA = ROOT / "schemas" / "proposals.schema.json"
NUTRITION_CSV = ROOT / "data" / "nutrition" / "Schweizer_Nahrwertdatenbank(Generische Lebensmittel).csv"
TEMPLATE_HTML = ROOT / "templates" / "Das-schmeckt-Recipe-Preview-A4.html"
ARCHIVE_XML_DIR = PERSON_C / "data" / "rezepte_export"
TOPICMAP_ZIP = ROOT / "data" / "recipe-archive" / "rezepte_export_topicmap.sql.zip"
KEY_RE = re.compile(r"(sk-|bfl_|ghp_)[A-Za-z0-9_-]{20,}")
C_FILES = ("recipes.json", "review.json", "nutrition.json", "stage_c_log.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def new_run_dir(base: Path | None = None) -> Path:
    d = (base or RUNS_DIR) / datetime.now().strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_runs(base: Path | None = None) -> list[Path]:
    base = base or RUNS_DIR
    if not base.is_dir():
        return []
    return sorted((d for d in base.iterdir() if d.is_dir() and (d / "proposals.json").is_file()), reverse=True)


def add_timing(run_dir: Path, key: str, seconds: float) -> None:
    p = run_dir / "timings.json"
    t = _read(p) if p.is_file() else {}
    t[key] = round(seconds, 1)
    _write(p, t)


# ----------------------------------------------------------------------------- Person A
def person_a_available() -> bool:
    return (ROOT / "data" / "trends" / "google-trends").is_dir()


def run_person_a(run_dir: Path, llm: bool = True, progress=None) -> dict:
    """Person A's real pipeline (Google Trends CSVs, live Wikimedia, brand fit, archive check, ranking) -> proposals.json."""
    from src.challenge2.orchestrator import ChallengeOrchestrator
    manifest = Path(os.environ.get("DAS_SCHMECKT_ARCHIVE_MANIFEST") or (PERSON_C / "data" / "auswahl_manifest.json"))
    t0 = time.time()
    orchestrator = ChallengeOrchestrator(log_path=run_dir / "decisions.jsonl", archive_manifest=manifest if manifest.is_file() else None)
    payload = orchestrator.generate_proposals(limit=5, llm=llm, progress=progress)
    try:
        import jsonschema
        jsonschema.validate(payload, _read(SCHEMA))
        payload["_schema"] = "valid"
    except ImportError:
        payload["_schema"] = "not checked (jsonschema missing)"
    except Exception as exc:  # noqa: BLE001
        payload["_schema"] = f"INVALID: {str(exc)[:200]}"
    _write(run_dir / "proposals.json", payload)
    add_timing(run_dir, "person_a_seconds", time.time() - t0)
    return payload


def sparkline(proposal: dict, days: int = 14) -> list[tuple[str, int]]:
    """The last `days` daily Wikipedia pageviews of the pitch (empty when the series is not available)."""
    pts = ((proposal.get("trend") or {}).get("wikimedia") or {}).get("points") or []
    series = [(p.get("date"), int(p.get("value", 0))) for p in pts if isinstance(p, dict) and p.get("date") is not None]
    return series[-days:]


def google_signal(proposal: dict) -> dict:
    pts = (proposal.get("trend") or {}).get("points") or []
    first = pts[0] if pts and isinstance(pts[0], dict) else {}
    return {"interest": (proposal.get("trend") or {}).get("score"), "increase": first.get("increase_percent") or "",
            "period": f"{first.get('period_start', '')} – {first.get('period_end', '')}".strip(" –"), "source": first.get("source", "")}


def rising_topics_table(limit: int = 12) -> list[dict]:
    """The Google Trends rows Person A starts from (the evidence shown in step 1)."""
    import csv
    path = ROOT / "data" / "trends" / "google-trends" / "searched_with_rising-searches_topics_DE_20261018-1818_20261118-1818.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))[:limit]
    return [{"topic": r.get("topic", ""), "search_interest": r.get("search interest", ""), "increase": r.get("increase percent", "")} for r in rows]


# ----------------------------------------------------------------------------- Person B
def _split_notes(notes: str) -> list[str]:
    return [n.strip() for n in re.split(r"[\n;]+", notes or "") if n.strip()]


def editor_handoff(run_dir: Path, proposal_id: str, notes: str, selected_by: str = "editor desk") -> dict:
    """Person B's editor desk records the choice (validated batch, audit log) and hands over selection.json for Person C."""
    from editor.agents import Agents
    from editor.batch import load_batch, propose_from_batch
    from editor.workflow import EditorWorkflow, WorkflowError

    class HandoffWorkflow(EditorWorkflow):
        """The editor's choice as an audited decision; recipe generation is Person C's stage, not a stub here."""
        def choose(self, proposal_id: str, notes: str) -> dict:
            self._need("proposals")
            prop = next((p for p in self.proposals if p["id"] == proposal_id), None)
            if prop is None:
                raise WorkflowError(f"Unknown proposal: {proposal_id}")
            self._log("editor_selected", proposal=proposal_id, topic=prop["topic"], notes=notes)
            self.selected, self.notes, self.stage = prop, notes, "handoff"
            return prop

    batch = load_batch(run_dir / "proposals.json")
    wf = HandoffWorkflow(Agents(propose=propose_from_batch(batch)), log_path=run_dir / "editor_audit.jsonl",
                         cards_dir=run_dir / "editor_cards")
    wf.start()
    prop = wf.choose(proposal_id, notes)
    selection = {"picks": 1, "selected_ids": [proposal_id], "selected_by": selected_by, "timestamp": _now(),
                 "steering_notes": _split_notes(notes),
                 "selected_title": prop.get("title"), "batch_sha256": batch.sha256, "batch_warnings": batch.warnings}
    _write(run_dir / "selection.json", selection)
    return {"selection": selection, "trail": list(wf.trail), "batch_label": batch.source_label, "warnings": list(batch.warnings)}


# ----------------------------------------------------------------------------- Person C
def c_config(run_dir: Path):
    """Person C's Config with the repo's tracked data (nutrition CSV, template) and this run's output folder."""
    from c_pipeline.config import Config
    cfg = Config.from_env()
    cfg.nutrition_csv = NUTRITION_CSV if NUTRITION_CSV.is_file() else (PERSON_C / "data" / "nutrition.csv")
    cfg.template_html = TEMPLATE_HTML if TEMPLATE_HTML.is_file() else cfg.template_html
    cfg.output_dir = run_dir / "c"
    os.environ["ARCHIVE_DIR"] = str(ARCHIVE_XML_DIR) if ARCHIVE_XML_DIR.is_dir() else ""
    if TOPICMAP_ZIP.is_file():
        os.environ.setdefault("TOPICMAP_SQL_ZIP", str(TOPICMAP_ZIP))
    return cfg


def c_live_available() -> dict:
    cfg = c_config(RUNS_DIR / "_probe")
    return {"llm": bool(cfg.llm_base_url and cfg.llm_model and not cfg.offline), "images": bool(cfg.bfl_api_key and not cfg.offline),
            "nutrition_db": Path(cfg.nutrition_csv).is_file(), "archive": ARCHIVE_XML_DIR.is_dir()}


class _Listen:
    """Context manager: Person C's decision log -> UI progress callback."""
    def __init__(self, progress):
        self.progress = progress or (lambda stage, event, data: None)

    def __enter__(self):
        from c_pipeline.pipeline import Log
        Log.listeners.append(self.progress)
        return self

    def __exit__(self, *exc):
        from c_pipeline.pipeline import Log
        if self.progress in Log.listeners:
            Log.listeners.remove(self.progress)
        return False


def run_person_c(run_dir: Path, make_image: bool = True, servings: int = 4, progress=None) -> dict:
    """pipeline.run_stage_c on this run's proposals.json + selection.json; returns the files as dicts."""
    from c_pipeline import pipeline
    cfg = c_config(run_dir)
    t0 = time.time()
    with _Listen(progress):
        pipeline.run_stage_c(cfg, run_dir / "selection.json", run_dir / "proposals.json", run_dir / "c", make_image, servings)
    add_timing(run_dir, "person_c_seconds", time.time() - t0)
    return load_c_outputs(run_dir)


def editor_rounds_used(run_dir: Path, recipe_id: str) -> int:
    rv = run_dir / "c" / "review.json"
    if not rv.is_file():
        return 0
    return sum(1 for r in _read(rv) if r.get("recipe_id") == recipe_id and r.get("round_type") == "editor")


def send_back(run_dir: Path, recipe_id: str, comment: str, make_image: bool = True, progress=None) -> dict:
    """Editor sends one recipe back: pipeline.run_editor_round (revise -> review -> nutrition -> image -> re-render)."""
    from c_pipeline import pipeline
    cfg = c_config(run_dir)
    t0 = time.time()
    with _Listen(progress):
        pipeline.run_editor_round(cfg, recipe_id, comment, run_dir / "c", make_image)
    add_timing(run_dir, f"editor_round_{recipe_id}_{editor_rounds_used(run_dir, recipe_id)}_seconds", time.time() - t0)
    return load_c_outputs(run_dir)


def load_c_outputs(run_dir: Path) -> dict | None:
    cdir = run_dir / "c"
    if not (cdir / "recipes.json").is_file():
        return None
    out = {k[:-5]: _read(cdir / k) for k in C_FILES if (cdir / k).is_file()}
    out["recipes"] = out.get("recipes", [])
    out["review"] = out.get("review", [])
    out["nutrition"] = {n["recipe_id"]: n for n in out.get("nutrition", [])}
    out["log"] = out.pop("stage_c_log", {"events": []})
    cards = cdir / "cards"
    out["cards"] = {r["id"]: cards / f"{r['id']}.html" for r in out["recipes"] if (cards / f"{r['id']}.html").is_file()}
    out["combined"] = cards / "das_schmeckt_rezepte.html" if (cards / "das_schmeckt_rezepte.html").is_file() else None
    for r in out["recipes"]:                      # image paths: absolute on the machine that ran it -> resolve for this run
        img = r.get("image") or {}
        if img.get("path"):
            cand = Path(img["path"])
            if not cand.is_file():
                cand = cdir / "img" / Path(img["path"]).name
            img["resolved_path"] = str(cand) if cand.is_file() else None
    return out


def page_count(card_path: Path | None) -> int | None:
    if not card_path or not Path(card_path).is_file():
        return None
    return len(re.findall(r'class="page"', Path(card_path).read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- run state
def load_run(run_dir: Path, mode: str = "live") -> dict:
    """Everything the page shows, read from the run folder (works for live runs and the demo cache alike)."""
    run = {"dir": run_dir, "mode": mode, "proposals": None, "selection": None, "handoff": None, "c": None, "timings": {}}
    if (run_dir / "proposals.json").is_file():
        run["proposals"] = _read(run_dir / "proposals.json")
    if (run_dir / "selection.json").is_file():
        run["selection"] = _read(run_dir / "selection.json")
    if (run_dir / "editor_audit.jsonl").is_file():
        run["handoff"] = {"trail": [json.loads(l) for l in (run_dir / "editor_audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]}
    if (run_dir / "timings.json").is_file():
        run["timings"] = _read(run_dir / "timings.json")
    run["c"] = load_c_outputs(run_dir)
    return run


# ----------------------------------------------------------------------------- demo cache
def scan_for_keys(paths: list[Path]) -> list[str]:
    hits = []
    for p in paths:
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if KEY_RE.search(text):
            hits.append(str(p))
    return hits


def save_demo_cache(run_dir: Path, dest: Path | None = None) -> Path:
    """Copy one finished run into the committed demo cache: JSON + cards + images, relative image paths, no keys."""
    dest = dest or DEMO_DIR
    if not (run_dir / "proposals.json").is_file() or not (run_dir / "c" / "recipes.json").is_file():
        raise ValueError("the run is not complete (needs proposals.json and c/recipes.json)")
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "c" / "cards").mkdir(parents=True)
    (dest / "c" / "img").mkdir(parents=True)
    for name in ("proposals.json", "selection.json", "editor_audit.jsonl", "timings.json"):
        if (run_dir / name).is_file():
            shutil.copy(run_dir / name, dest / name)
    for name in C_FILES:
        if (run_dir / "c" / name).is_file():
            shutil.copy(run_dir / "c" / name, dest / "c" / name)
    for f in (run_dir / "c" / "cards").glob("*.html"):
        shutil.copy(f, dest / "c" / "cards" / f.name)
    for f in (run_dir / "c" / "img").glob("*.jpg"):
        shutil.copy(f, dest / "c" / "img" / f.name)
    recipes = _read(dest / "c" / "recipes.json")
    for r in recipes:                               # machine paths out, relative paths in
        img = r.get("image") or {}
        if img.get("path"):
            img["path"] = f"c/img/{Path(img['path']).name}"
        img.pop("resolved_path", None)
    _write(dest / "c" / "recipes.json", recipes)
    log = _read(dest / "c" / "stage_c_log.json")
    for e in log.get("events", []):
        for k, v in list(e.items()):
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                e[k] = [x.replace(str(run_dir), "<run>") for x in v]
            elif isinstance(v, str):
                e[k] = v.replace(str(run_dir), "<run>")
    _write(dest / "c" / "stage_c_log.json", log)
    hits = scan_for_keys([p for p in dest.rglob("*") if p.is_file()])
    if hits:
        shutil.rmtree(dest)
        raise ValueError("key-shaped strings found, cache not written: " + ", ".join(hits))
    _write(dest / "META.json", {"cached_at": _now(), "from_run": run_dir.name, "note": "real live run, replayed in demo mode"})
    return dest


def demo_available() -> bool:
    return (DEMO_DIR / "proposals.json").is_file() and (DEMO_DIR / "c" / "recipes.json").is_file()


# ----------------------------------------------------------------------------- impact panel (measured only)
def impact_metrics(c: dict | None, timings: dict | None = None) -> dict:
    """Numbers from stage_c_log.json, review.json and nutrition.json only. Missing data stays missing."""
    m: dict = {"seconds_per_stage": {}, "issues_caught": 0, "corrections": 0, "review_rounds": 0,
               "nutrition": {}, "image_scores": {}, "person_a_seconds": (timings or {}).get("person_a_seconds"),
               "person_c_seconds": (timings or {}).get("person_c_seconds")}
    if not c:
        return m
    events = (c.get("log") or {}).get("events") or []
    prev = 0.0
    for e in events:                                 # the time until an event belongs to the stage that reported it
        t = float(e.get("t", prev))
        m["seconds_per_stage"][e.get("stage", "?")] = round(m["seconds_per_stage"].get(e.get("stage", "?"), 0.0) + (t - prev), 1)
        prev = t
    for rv in c.get("review", []):
        m["review_rounds"] += 1
        for v in list((rv.get("criteria") or {}).values()) + list((rv.get("extras") or {}).values()):
            if not v.get("pass"):
                m["issues_caught"] += len([i for i in v.get("issues", []) if not str(i).startswith("Hinweis")]) or 1
    for r in c.get("recipes", []):
        m["corrections"] += sum(len(h.get("changes") or []) for h in r.get("history") or [])
        v = (r.get("image") or {}).get("verification")
        if isinstance(v, dict):
            m["image_scores"][r["id"]] = {"score": v.get("score"), "retried": v.get("retried"), "model": v.get("model")}
        else:
            m["image_scores"][r["id"]] = {"score": None, "note": v}
    for rid, n in (c.get("nutrition") or {}).items():
        cov = n.get("coverage") or {}
        m["nutrition"][rid] = {"matched": cov.get("ingredients_calculated"), "of": cov.get("ingredients_needing_calc"),
                               "share": cov.get("share"), "quality": cov.get("quality"), "kcal": (n.get("per_serving") or {}).get("kcal"),
                               "closest": sum(1 for x in n.get("ingredients", []) if x.get("match") == "closest_category")}
    return m
