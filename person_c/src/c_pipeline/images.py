"""Image generation with Black Forest Labs FLUX (async API: submit -> poll `polling_url` -> download)
plus a vision check that the picture really shows the recipe.

Verified against docs.bfl.ai (Nov 2026): POST {base}/{model} with header `x-key`, JSON {prompt, width, height,
output_format}; response {id, polling_url}; poll polling_url until status == "Ready"; result.sample is a signed URL
valid for ~10 minutes -> download immediately. Never fails the pipeline: returns status "placeholder" instead.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Config

STYLE_SUFFIX = ("Medium close-up, camera about 35-45 cm from the dish, 45-degree angle, the dish fills about 70% of "
                "the frame, the rim of the vessel partly cropped, shallow depth of field, visible texture of the food, "
                "warm natural daylight, calm but atmospheric background (not sterile), appetizing, avoid a dominant "
                "green colour cast, no text, no logos, no people or hands, no extra food items. Do not go extreme "
                "macro: the whole composition must still read as the dish.")
_FAIL = ("error", "failed", "request moderated", "content moderated")

# --- vision check -------------------------------------------------------------------------------
# A vision-capable model on the gateway; tried when the configured model cannot read pictures.
VISION_FALLBACK_MODEL = "Qwen/Qwen3-VL-235B-A22B-Instruct-FP8"
VISION_SYSTEM = ("You are a picky food photo editor. You report only what you really see in the picture. "
                 "You answer with a single JSON object and nothing else.")
MIN_SCORE = 7
NEVER_SHOW = ("garnish", "fresh herbs", "parsley", "lemon", "bread", "side dishes", "salad", "sauce swirls",
              "dips", "extra plates of food", "cutlery with food on it")


def build_prompt(recipe_prompt: str, brand_style: str | None = None) -> str:
    return f"{recipe_prompt.strip().rstrip('.')}. {brand_style or STYLE_SUFFIX}"


def generate_image(prompt: str, out_path: str | Path, cfg: Config, timeout_s: int = 150) -> dict:
    meta = {"model": cfg.bfl_model, "prompt": prompt, "path": None, "status": "placeholder",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": None}
    if cfg.offline or not cfg.bfl_api_key:
        meta["note"] = "offline mode or BFL_API_KEY missing – placeholder shown on the card"
        return meta
    headers = {"accept": "application/json", "x-key": cfg.bfl_api_key, "Content-Type": "application/json"}
    try:
        r = requests.post(f"{cfg.bfl_base_url.rstrip('/')}/{cfg.bfl_model}", headers=headers, timeout=60,
                          json={"prompt": prompt, "width": cfg.image_size, "height": cfg.image_size, "output_format": "jpeg"})
        if r.status_code >= 400:
            raise RuntimeError(f"submit HTTP {r.status_code}: {r.text[:200]}")
        job = r.json()
        meta["request_id"] = job.get("id")
        poll = job["polling_url"]
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(0.7)
            pr = requests.get(poll, headers={"accept": "application/json", "x-key": cfg.bfl_api_key}, timeout=30)
            pr.raise_for_status()
            res = pr.json()
            status = str(res.get("status", ""))
            if status == "Ready":
                url = res["result"]["sample"]
                img = requests.get(url, timeout=60)
                img.raise_for_status()
                out = Path(out_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(img.content)
                meta.update(path=str(out), status="generated", cost=job.get("cost"))
                return meta
            if status.lower() in _FAIL:
                raise RuntimeError(f"generation status: {status}")
        raise RuntimeError("timeout while polling")
    except Exception as e:  # noqa: BLE001 – image problems must never stop the editorial workflow
        meta["note"] = f"image generation failed: {e}"
        return meta


def component_names(recipe: dict) -> list[str]:
    """German names of the ingredients listed in `image_components` (fallback: all ingredients)."""
    ids = recipe.get("image_components")
    ings = recipe.get("ingredients", [])
    if not ids:
        return [i["name"] for i in ings]
    by_id = {i.get("id"): i for i in ings}
    return [by_id[i]["name"] for i in ids if i in by_id]


def reinforced_prompt(recipe_prompt: str, must_show: list[str], must_not_show: list[str]) -> str:
    """Second attempt: the same dish, but with the two lists spelled out for the image model."""
    must = ", ".join(must_show) or "the finished dish"
    nots = ", ".join(dict.fromkeys([*must_not_show, *NEVER_SHOW]))
    return (f"{recipe_prompt.strip().rstrip('.')}. MUST show: {must}. "
            f"MUST NOT show: {nots}. Nothing on the picture that is not part of this dish. {STYLE_SUFFIX}")


def _verification_errors(o) -> list[str]:
    if not isinstance(o, dict):
        return ["reply must be a JSON object"]
    s = o.get("matches_recipe_score")
    if not isinstance(s, (int, float)) or isinstance(s, bool) or not 0 <= s <= 10:
        return ["matches_recipe_score must be a number 0-10"]
    for k in ("visible_foods", "foods_not_in_recipe", "missing_components"):
        if not isinstance(o.get(k), list):
            return [f"{k} must be a list"]
    return []


def verify_image(client, image_path: str | Path, recipe: dict, components: list[str],
                 models: list[str | None]) -> tuple[dict | None, list[str]]:
    """Ask a vision model what is on the picture. Returns (result, errors); result is None if no model could answer."""
    text = (f"TASK: image_verify:{recipe.get('id', 'r')}\n"
            f"Dish: {recipe['title']}\n"
            f"Components that belong in the picture: {', '.join(components) or '(none)'}\n\n"
            'Look at the picture and reply with JSON only: {"visible_foods": ["..."], "matches_recipe_score": <0-10>, '
            '"foods_not_in_recipe": ["..."], "missing_components": ["..."]}.\n'
            "visible_foods: every food you can actually see. matches_recipe_score: how well the picture shows exactly "
            "this dish (10 = exactly this dish, nothing else). foods_not_in_recipe: foods on the picture that are not "
            "in the component list (garnish, herbs, lemon, bread, side dishes, sauces). missing_components: components "
            "from the list that you cannot see.")
    errors: list[str] = []
    for m in models:
        try:
            res = client.chat_vision_json(VISION_SYSTEM, text, image_path, validate=_verification_errors,
                                          retries=1, temperature=0.0, model=m)
            res["model"] = m or "(configured model)"
            return res, errors
        except Exception as e:  # noqa: BLE001 – a model without vision must not stop the workflow
            errors.append(f"{m or '(configured model)'}: {str(e)[:160]}")
    return None, errors


def _needs_retry(v: dict) -> bool:
    return float(v["matches_recipe_score"]) < MIN_SCORE or bool(v["foods_not_in_recipe"])


def _rank(v: dict | None) -> tuple[int, float]:
    """Better = no foreign food first, then the higher score."""
    if v is None:
        return (-1, -1.0)
    return (0 if v["foods_not_in_recipe"] else 1, float(v["matches_recipe_score"]))


def _attempt(n: int, prompt: str, v: dict | None, note: str | None = None) -> dict:
    a = {"attempt": n, "prompt": prompt, "note": note}
    if v:
        a.update(model=v.get("model"), score=v["matches_recipe_score"], visible_foods=v["visible_foods"],
                 foods_not_in_recipe=v["foods_not_in_recipe"], missing_components=v["missing_components"])
    return a


def generate_and_verify(recipe: dict, cfg: Config, client, out_dir: str | Path, log=None) -> dict:
    """FLUX image -> vision check -> at most one reinforced retry, keeping the better of the two pictures.

    The whole verification (both attempts) ends up in recipe["image"]["verification"]; a missing vision model is
    recorded as "nicht verfügbar" and never raises.
    """
    def _log(event, **data):
        if log is not None:
            log.add("image", event, **data)

    rid = recipe["id"]
    path = Path(out_dir) / "img" / f"{rid}.jpg"
    base = recipe["image_prompt"]
    meta = generate_image(build_prompt(base), path, cfg)
    meta["prompt_source"] = base
    _log(f"{rid}: {meta['status']}", note=meta.get("note"))
    if meta["status"] != "generated":
        meta["verification"] = "nicht verfügbar"
        meta["verification_note"] = meta.get("note") or "kein Bild erzeugt"
        return meta
    comps = component_names(recipe)
    models: list[str | None] = [None] if cfg.llm_model == VISION_FALLBACK_MODEL else [None, VISION_FALLBACK_MODEL]
    v1, errs = verify_image(client, path, recipe, comps, models)
    if v1 is None:
        meta["verification"] = "nicht verfügbar"
        meta["verification_note"] = "kein Vision-Modell verfügbar: " + "; ".join(errs)[:400]
        _log(f"{rid}: verification nicht verfügbar", errors=errs[:2])
        return meta
    attempts = [_attempt(1, base, v1)]
    _log(f"{rid}: verification score {v1['matches_recipe_score']}/10", model=v1["model"],
         foods_not_in_recipe=v1["foods_not_in_recipe"], missing=v1["missing_components"])
    kept, best = 1, v1
    if _needs_retry(v1):
        p2 = reinforced_prompt(base, comps, [str(f) for f in v1["foods_not_in_recipe"]])
        alt_path = path.with_name(f"{rid}_attempt2.jpg")
        meta2 = generate_image(p2, alt_path, cfg)
        v2, errs2 = (None, [])
        if meta2["status"] == "generated":
            v2, errs2 = verify_image(client, alt_path, recipe, comps, models)
        attempts.append(_attempt(2, p2, v2, note=meta2.get("note") or ("; ".join(errs2)[:200] or None)))
        _log(f"{rid}: retry score {v2['matches_recipe_score'] if v2 else 'n/a'}/10",
             kept="attempt 2" if _rank(v2) > _rank(v1) else "attempt 1")
        if _rank(v2) > _rank(v1):
            alt_path.replace(path)
            meta2.update(path=str(path), prompt_source=base)
            meta, kept, best = meta2, 2, v2
        elif alt_path.exists():
            alt_path.unlink()
    meta["verification"] = {
        "status": "geprüft", "model": best["model"], "min_score": MIN_SCORE,
        "score": best["matches_recipe_score"], "foods_not_in_recipe": best["foods_not_in_recipe"],
        "missing_components": best["missing_components"], "components": comps,
        "retried": len(attempts) > 1, "kept_attempt": kept, "attempts": attempts,
    }
    return meta
