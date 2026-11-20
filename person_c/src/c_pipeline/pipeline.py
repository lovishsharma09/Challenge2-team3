"""Stages 06-09 orchestration (Person C): recipes -> review/correction loop -> images -> nutrition -> HTML cards.

Outputs (CONTRACTS.md): recipes.json, review.json, nutrition.json, cards/*.html, img/*, stage_c_log.json
Entry points for Person B's orchestrator / editor UI:  run_stage_c(...)  and  run_editor_round(...)
"""
from __future__ import annotations
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .archive import ArchiveIndex, load_topicmap
from .config import Config, ROOT
from .images import generate_and_verify
from .llm import get_client
from .nutrition_agent import compute_nutrition
from .nutrition_db import NutritionDB
from .recipe_agent import faithful_image_prompt, generate_recipes, load_brand_rules, revise_recipe
from .render import build_document, extract_template_logo, image_to_uri, render_recipe_pages
from .review_agent import review_recipe


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Log:
    """Every decision/assumption goes here (feeds Person B's decision log + the impact panel)."""
    def __init__(self):
        self.events: list[dict] = []
        self.t0 = time.time()

    def add(self, stage: str, event: str, **data):
        self.events.append({"t": round(time.time() - self.t0, 1), "stage": stage, "event": event, **data})
        print(f"[{stage}] {event}" + (f" {json.dumps(data, ensure_ascii=False)[:160]}" if data else ""))


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(out: Path, log: Log) -> None:
    """stage_c_log.json stays the single decision log: a partial run (images, nutrition) appends its events."""
    p = out / "stage_c_log.json"
    meta = _read(p) if p.exists() else {"generated_at": _now(), "events": []}
    meta["events"] = (meta.get("events") or []) + log.events
    meta["updated_at"] = _now()
    _write(p, meta)


def ensure_image_prompt(recipe: dict, client, log: Log) -> None:
    """Derive `image_components` + an English `image_prompt` from the recipe itself (once per recipe version).

    Without it the picture shows whatever the text prompt happened to say; with it the prompt lists exactly the
    components that are visible in the finished dish. Failures keep the existing prompt – no picture is worth a crash.
    """
    if recipe.get("image_components"):
        return
    try:
        res = faithful_image_prompt(client, recipe)
    except Exception as e:  # noqa: BLE001
        log.add("image", f"{recipe['id']}: faithful image prompt unavailable – the recipe's own prompt is used",
                error=str(e)[:160])
        return
    recipe["image_components"], recipe["image_prompt"] = res["components"], res["prompt"]
    log.add("image", f"{recipe['id']}: image prompt derived from the recipe", components=res["components"],
            prompt=res["prompt"])


def load_archive(cfg: Config, log: Log) -> ArchiveIndex | None:
    import os
    d = Path(os.environ.get("ARCHIVE_DIR", ""))
    if not d.is_dir():
        log.add("archive", "archive folder not found – differentiation vs archive skipped (set ARCHIVE_DIR)")
        return None
    tm = None
    z = os.environ.get("TOPICMAP_SQL_ZIP")
    if z and Path(z).is_file():
        try:
            tm = load_topicmap(z)
        except Exception as e:  # noqa: BLE001
            log.add("archive", "topic map could not be parsed", error=str(e)[:120])
    idx = ArchiveIndex.load_dir(d, tm)
    log.add("archive", "archive loaded", recipes=len(idx.records), topicmap=bool(tm))
    return idx


def load_db(cfg: Config, log: Log) -> NutritionDB | None:
    p = cfg.nutrition_csv
    if p and Path(p).is_file():
        db = NutritionDB.load(p)
        log.add("nutrition", "database loaded", entries=len(db.entries), version=db.version, synthetic=db.is_fixture)
        return db
    log.add("nutrition", "NUTRITION_CSV not found – nutrition values cannot be calculated")
    return None


# ----------------------------------------------------------------------------- review loop
def review_loop(client_recipe, client_review, recipe: dict, sibling: dict | None, idx: ArchiveIndex | None,
                brand: dict, steering: list[str], cfg: Config, log: Log, rounds: list[dict],
                start_iteration: int = 1, round_type: str = "auto", editor_comment: str | None = None) -> dict:
    """review -> (revise -> review)* with at most cfg.max_auto_revisions corrections."""
    revisions = 0
    it = start_iteration
    while True:
        matches = idx.similar(recipe["title"], [i["name"] for i in recipe["ingredients"]], 5) if idx else []
        rv = review_recipe(client_review, recipe, sibling, matches, brand, it, round_type, editor_comment)
        rounds.append(rv)
        n_fail = sum(1 for v in {**rv["criteria"], **rv["extras"]}.values() if not v["pass"])
        log.add("review", f"{recipe['id']} v{recipe.get('version', 1)} iteration {it}: {rv['overall']}", failing=n_fail, llm=rv["llm_used"])
        if rv["overall"] == "pass" or revisions >= cfg.max_auto_revisions:
            if rv["overall"] != "pass":
                log.add("review", f"{recipe['id']}: correction limit reached ({cfg.max_auto_revisions}) – open issues stay visible for the editor")
            recipe["review_status"] = rv["overall"]
            return recipe
        recipe, change_log = revise_recipe(client_recipe, recipe, rv["correction_report"], editor_comment, steering)
        recipe.setdefault("history", []).append({"version": recipe["version"], "reason": rv["correction_report"], "changes": change_log})
        revisions += 1
        it += 1
        log.add("recipe", f"{recipe['id']} revised to v{recipe['version']}", changes=len(change_log))
        round_type, editor_comment = "auto", None


# ----------------------------------------------------------------------------- finish: images, nutrition, cards
def finish_recipe(recipe: dict, cfg: Config, db: NutritionDB | None, client, log: Log, out: Path, make_image: bool = True) -> tuple[dict, dict | None]:
    if make_image:
        ensure_image_prompt(recipe, client, log)
        img_meta = recipe.get("image") or {}
        if img_meta.get("prompt_source") != recipe["image_prompt"] or not img_meta.get("path"):
            recipe["image"] = generate_and_verify(recipe, cfg, client, out, log)
    nut = None
    if db is not None:
        nut = compute_nutrition(recipe, db, client)
        log.add("nutrition", f"{recipe['id']}: per serving {nut['per_serving'].get('kcal')} kcal", quality=nut["coverage"]["quality"],
                unmatched=len(nut["unmatched"]))
    return recipe, nut


def render_outputs(recipes: list[dict], nutrition: list[dict | None], cfg: Config, out: Path, log: Log) -> dict:
    logo = extract_template_logo(cfg.template_html)
    if cfg.template_html and not logo:
        log.add("render", "logo not found in template – text wordmark used")
    sections, files = [], []
    for r, n in zip(recipes, nutrition):
        pages = render_recipe_pages(r, n, image_to_uri((r.get("image") or {}).get("path")), logo, True)
        sections.append((r["title"], pages))
        p = out / "cards" / f"{r['id']}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_document([(r["title"], pages)]), encoding="utf-8")
        files.append({"recipe_id": r["id"], "path": str(p), "pages": len(pages)})
    both = out / "cards" / "das_schmeckt_rezepte.html"
    both.write_text(build_document(sections), encoding="utf-8")
    log.add("render", "cards written", files=[f["path"] for f in files], pages=[f["pages"] for f in files])
    return {"cards": files, "combined": str(both)}


def _save(out: Path, recipes, rounds, nutrition, log: Log, extra: dict):
    _write(out / "recipes.json", recipes)
    _write(out / "review.json", rounds)
    _write(out / "nutrition.json", [n for n in nutrition if n])
    _write(out / "stage_c_log.json", {"generated_at": _now(), **extra, "events": log.events})


# ----------------------------------------------------------------------------- main entry points
def run_stage_c(cfg: Config, selection_path: Path, proposals_path: Path, out: Path | None = None,
                make_image: bool = True, servings: int = 4) -> dict:
    out = Path(out or cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = Log()
    sel, props = _read(selection_path), _read(proposals_path)
    pid = sel["selected_ids"][0]
    # Person A's live handoff is {"proposals": [...], "rejected_topics": [...]} (schemas/proposals.schema.json);
    # CONTRACTS.md documents {"recommended": [...], "rejected": [...]}. Accept both, fail with a readable message.
    candidates = props.get("recommended") or props.get("proposals") or []
    proposal = next((p for p in candidates if p.get("id") == pid), None)
    if proposal is None:
        raise ValueError(f"selected proposal '{pid}' not found in proposals.json (ids: {[p.get('id') for p in candidates]})")
    steering = sel.get("steering_notes") or []
    log.add("selection", f"editor selected {pid}: {proposal['title']}", steering=steering, picks=sel.get("picks"))

    client = get_client(cfg)
    client_review = get_client(replace(cfg, llm_model=cfg.review_model or cfg.llm_model))
    brand = load_brand_rules(cfg)
    idx, db = load_archive(cfg, log), load_db(cfg, log)
    titles = idx.titles_for_prompt(proposal["title"].split() + sum([i.split() for i in proposal.get("recipe_ideas", [])], []), 12) if idx else []

    recipes = generate_recipes(client, proposal, steering, brand, titles, servings)
    log.add("recipe", "generated 2 recipes", titles=[r["title"] for r in recipes], differentiation=[r.get("differentiation") for r in recipes])

    rounds: list[dict] = []
    for n, r in enumerate(recipes):
        sibling = recipes[1 - n]
        recipes[n] = review_loop(client, client_review, r, sibling, idx, brand, steering, cfg, log, rounds)
    nutrition: list[dict | None] = []
    for n, r in enumerate(recipes):
        recipes[n], nut = finish_recipe(r, cfg, db, client, log, out, make_image)
        nutrition.append(nut)
    cards = render_outputs(recipes, nutrition, cfg, out, log)
    _save(out, recipes, rounds, nutrition, log, {"models": {"recipe": cfg.llm_model, "review": cfg.review_model or cfg.llm_model, "image": cfg.bfl_model},
                                                  "offline": cfg.offline, "proposal_id": pid, "steering_notes": steering})
    return {"recipes": recipes, "review": rounds, "nutrition": nutrition, **cards}


def run_editor_round(cfg: Config, recipe_id: str, comment: str, out: Path | None = None, make_image: bool = True) -> dict:
    """Editor sends a recipe back with a comment: revise -> review again -> re-nutrition -> re-render (max 2 per recipe)."""
    out = Path(out or cfg.output_dir)
    log = Log()
    recipes, rounds = _read(out / "recipes.json"), _read(out / "review.json")
    meta = _read(out / "stage_c_log.json")
    nutrition = {n["recipe_id"]: n for n in (_read(out / "nutrition.json") if (out / "nutrition.json").exists() else [])}
    done = sum(1 for r in rounds if r["recipe_id"] == recipe_id and r["round_type"] == "editor")
    if done >= cfg.max_editor_rounds:
        raise RuntimeError(f"editor round limit reached for {recipe_id} ({cfg.max_editor_rounds})")
    n = next(i for i, r in enumerate(recipes) if r["id"] == recipe_id)
    client = get_client(cfg)
    client_review = get_client(replace(cfg, llm_model=cfg.review_model or cfg.llm_model))
    brand, idx, db = load_brand_rules(cfg), load_archive(cfg, log), load_db(cfg, log)
    steering = meta.get("steering_notes") or []
    log.add("editor", f"{recipe_id} sent back by editor", comment=comment)
    cur = recipes[n]
    new, change_log = revise_recipe(client, cur, "(Editor-Rückmeldung, siehe Kommentar)", comment, steering)
    new.setdefault("history", cur.get("history", []))
    new["history"].append({"version": new["version"], "reason": f"Editor: {comment}", "changes": change_log})
    it = 1 + max(r["iteration"] for r in rounds if r["recipe_id"] == recipe_id)
    recipes[n] = review_loop(client, client_review, new, recipes[1 - n] if len(recipes) > 1 else None, idx, brand, steering, cfg, log, rounds,
                             start_iteration=it, round_type="editor", editor_comment=comment)
    recipes[n], nut = finish_recipe(recipes[n], cfg, db, client, log, out, make_image)
    nutrition[recipe_id] = nut
    ordered = [nutrition.get(r["id"]) for r in recipes]
    cards = render_outputs(recipes, ordered, cfg, out, log)
    meta["events"] += log.events
    _write(out / "recipes.json", recipes); _write(out / "review.json", rounds)
    _write(out / "nutrition.json", [x for x in ordered if x]); _write(out / "stage_c_log.json", meta)
    return {"recipe": recipes[n], "review": rounds[-1], **cards}


def render_only(cfg: Config, out: Path | None = None) -> dict:
    """Re-render cards from existing recipes.json / nutrition.json (no LLM, no image calls). Instant."""
    out = Path(out or cfg.output_dir)
    log = Log()
    recipes = _read(out / "recipes.json")
    nut = {n["recipe_id"]: n for n in (_read(out / "nutrition.json") if (out / "nutrition.json").exists() else [])}
    cards = render_outputs(recipes, [nut.get(r["id"]) for r in recipes], cfg, out, log)
    return {"recipes": recipes, **cards}


def renutrition(cfg: Config, out: Path | None = None) -> dict:
    """Recompute nutrition for the existing recipes (keeps recipes/images), then re-render the cards."""
    out = Path(out or cfg.output_dir)
    log = Log()
    recipes = _read(out / "recipes.json")
    db = load_db(cfg, log)
    if db is None:
        raise RuntimeError("NUTRITION_CSV not found")
    client = get_client(cfg)
    nutrition = []
    for r in recipes:
        n = compute_nutrition(r, db, client)
        nutrition.append(n)
        log.add("nutrition", f"{r['id']}: per serving {n['per_serving'].get('kcal')} kcal", quality=n["coverage"]["quality"],
                matched=n["coverage"]["ingredients_calculated"], of=n["coverage"]["ingredients_needing_calc"],
                unmatched=[u["original"] for u in n["unmatched"]], negligible=[u["original"] for u in n.get("negligible", [])])
    _write(out / "nutrition.json", nutrition)
    cards = render_outputs(recipes, nutrition, cfg, out, log)
    _append_log(out, log)
    return {"nutrition": nutrition, **cards}


def images_only(cfg: Config, out: Path | None = None) -> dict:
    """Generate (or regenerate) the FLUX images for the existing recipes, then re-render. Text and nutrition stay untouched."""
    out = Path(out or cfg.output_dir)
    log = Log()
    recipes = _read(out / "recipes.json")
    nut = {n["recipe_id"]: n for n in (_read(out / "nutrition.json") if (out / "nutrition.json").exists() else [])}
    try:
        client = get_client(cfg)
    except Exception as e:  # noqa: BLE001 – without an LLM the stored prompt is used and nothing is verified
        log.add("image", "no LLM client – prompts are not rebuilt and pictures are not verified", error=str(e)[:160])
        client = None
    for r in recipes:
        ensure_image_prompt(r, client, log)
        r["image"] = generate_and_verify(r, cfg, client, out, log)
    _write(out / "recipes.json", recipes)
    cards = render_outputs(recipes, [nut.get(r["id"]) for r in recipes], cfg, out, log)
    _append_log(out, log)
    return {"recipes": recipes, **cards}
