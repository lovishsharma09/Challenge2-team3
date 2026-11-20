"""Bridge to Person C's pipeline (person_c/src/c_pipeline): recipe generation, review, revision and nutrition.

Our workflow (editor/workflow.py) stays the CONTROLLER: hard issues block approval, a revised draft replaces the shown one only after its own
review, nothing is exported before approval. This module only supplies the agents behind our `Agents(...)` seam and converts shapes in
both directions. Person C's recipe object travels with every recipe under "_c" so nothing is lost when C's code revises or renders it.

Privacy rules (docs/decisions.md): the pitch handed to C carries only the pitch's own text. No archive titles, matches or dates are ever put
into a prompt. Live mode sends pitch and recipe text to the hackathon text gateway (Tesseracted); it never uses image generation.
"""
from __future__ import annotations

import copy
import re
import sys
from dataclasses import replace
from pathlib import Path

from .agents import Agents
from .llm import _env

REPO = Path(__file__).resolve().parent.parent
C_SRC = REPO / "person_c" / "src"
REAL_NUTRITION_CSV = REPO / "data" / "nutrition" / "Schweizer_Nahrwertdatenbank(Generische Lebensmittel).csv"
MOCK_NUTRITION_CSV = REPO / "person_c" / "fixtures" / "nutrition_mini_SYNTHETIC.csv"

# Person C's criteria that are verified by code get a family so they are not reported twice next to our own hard checks.
C_FAMILY = {"all_ingredients_used": "unused", "quantity_completeness": "quantity", "units_consistent": "units", "tbsp_tsp": "units"}
# Only DATA-level checks may block approval (a missing quantity, an ingredient that no step uses). Findings that come from parsing free text
# (units, spoon sizes, plausibility, step order) are heuristics: a live run showed "je 1 TL (insgesamt 4 TL)" flagged as a mismatch. They stay visible as soft findings.
HARD_C = {"quantity_completeness", "all_ingredients_used"}
MAX_SOFT_PER_CRITERION = 2
# an LLM remark that merely explains that an automatic warning is a false alarm is not an issue
DISMISSAL = re.compile(r"fehlalarm|false alarm|kein fehler|no error|\bist (korrekt|richtig|plausibel|in ordnung)\b|korrekt (hochgerechnet|angegeben|umgerechnet)"
                       r"|\bstimm\w* .{0,60}\büberein|\bübereinstimm|keine (weiteren |weiteren )?(probleme|abweichungen|auffälligkeiten)", re.I)


class CUnavailable(RuntimeError):
    """Person C's package is missing or cannot be imported."""


def _import_c():
    if not (C_SRC / "c_pipeline").is_dir():
        raise CUnavailable("Person C's package was not found (person_c/src/c_pipeline). Merge main into this branch.")
    if str(C_SRC) not in sys.path:
        sys.path.insert(0, str(C_SRC))
    try:
        from c_pipeline import config, llm, nutrition_agent, nutrition_db, recipe_agent, review_agent
    except Exception as exc:  # noqa: BLE001
        raise CUnavailable(f"Person C's package could not be imported: {type(exc).__name__}: {exc}") from None
    return config, llm, nutrition_agent, nutrition_db, recipe_agent, review_agent


# ------------------------------------------------------------------ shape conversion
def proposal_to_c(proposal: dict) -> dict:
    """The pitch as Person C's recipe prompt needs it: the pitch's OWN text only. Archive blocks (titles, matches, dates) are left out on purpose."""
    trend = proposal.get("trend") if isinstance(proposal.get("trend"), dict) else {}
    brand = proposal.get("brand_fit") if isinstance(proposal.get("brand_fit"), dict) else {}
    return {"id": proposal.get("id"), "title": proposal.get("title"), "topic": proposal.get("topic"),
            "recipe_ideas": [i for i in proposal.get("recipe_ideas", []) if isinstance(i, str)],
            "why_now": trend.get("why_relevant"), "brand_fit_summary": brand.get("reasoning")}


def _int_or_none(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and float(x).is_integer() else x


def to_ours(c: dict, mock: bool) -> dict:
    """Person C recipe -> our recipe shape (title, subtitle, servings, times, ingredients with amount/unit, steps as text)."""
    ings = []
    for i in c.get("ingredients", []):
        note = f" ({i['note']})" if i.get("note") else ""
        ings.append({"name": f"{i.get('name', '')}{note}", "amount": _int_or_none(i.get("quantity")), "unit": i.get("unit") or "",
                     "countable": i.get("quantity") is not None and not i.get("unit")})
    servings = (c.get("servings") or {}).get("amount")
    times = c.get("times") or {}
    return {"title": c["title"], "subtitle": c.get("intro") or "", "servings": _int_or_none(servings) or 4,
            "prep_time_minutes": _int_or_none(times.get("prep_min")), "cook_time_minutes": _int_or_none(times.get("cook_min")),
            "ingredients": ings, "steps": [s["text"] for s in c.get("steps", [])], "serving_tip": c.get("serving_tip") or "",
            "image_url": None, "mock": mock, "_c": copy.deepcopy(c)}


def nutrition_to_ours(n: dict | None, synthetic: bool) -> dict:
    """Person C nutrition -> ours. A value is never invented: no kcal means "pending". Assumptions and gaps stay visible."""
    if not n or (n.get("per_serving") or {}).get("kcal") is None:
        return {"status": "pending", "per_serving": None, "assumptions": [], "synthetic": synthetic,
                "unmatched": [u.get("original") for u in (n or {}).get("unmatched", [])]}
    cov = n.get("coverage") or {}
    return {"status": "ok", "per_serving": dict(n["per_serving"]), "synthetic": synthetic,
            "assumptions": [{"original": i.get("original"), "used": i.get("db_name"), "confidence": i.get("confidence")}
                            for i in n.get("ingredients", []) if i.get("assumption")],
            "unmatched": [u.get("original") for u in n.get("unmatched", [])],
            "coverage_text": (f"Berechnet aus der Schweizer Nährwertdatenbank, Qualität: {cov.get('quality', '?')} "
                              f"({cov.get('ingredients_calculated', '?')} von {cov.get('ingredients_needing_calc', '?')} Zutaten)."),
            "_c": n}


def findings_from_review(rv: dict, recipe_index: int) -> list[dict]:
    """Person C review -> findings for our workflow. Only data-level code errors are HARD (they block approval); everything else is soft,
    de-duplicated and capped per criterion so the editor sees what matters instead of a wall of remarks."""
    out, seen, count = [], set(), {}
    for group in (rv.get("criteria") or {}, rv.get("extras") or {}):
        for criterion, verdict in group.items():
            for issue in verdict.get("issues", []):
                text = str(issue)
                if text.startswith("Hinweis:"):
                    kind, msg = "soft", text[len("Hinweis:"):].strip()
                elif text.startswith("[LLM]"):
                    kind, msg = "soft", text[len("[LLM]"):].strip()
                    if (verdict.get("pass", True) and not verdict.get("fix")) or DISMISSAL.search(msg):
                        continue                               # a remark on a passing criterion, or "this warning is a false alarm"
                else:                                          # an automatic code finding
                    kind, msg = ("hard" if criterion in HARD_C else "soft"), text.strip()
                key = (criterion, msg.casefold())
                if key in seen:
                    continue
                seen.add(key)
                if kind == "soft":
                    count[criterion] = count.get(criterion, 0) + 1
                    if count[criterion] > MAX_SOFT_PER_CRITERION:
                        continue
                out.append({"recipe_index": recipe_index, "criterion": criterion, "message": msg, "kind": kind,
                            "family": C_FAMILY.get(criterion, "") if kind == "hard" else ""})
    return out


class ImageChecksOff:
    """Wraps Person C's client for OUR use: we generate no images, so C's strict image-prompt checks (image_prompt / image_components)
    must not reject an otherwise valid recipe and force a full regeneration. Every other validation problem is kept and still retried."""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        return getattr(self._client, name)

    def chat_json(self, system, user, *, validate=None, **kw):
        def relaxed(obj):
            return [p for p in (validate(obj) if validate else []) if "image_prompt" not in p and "image_components" not in p]
        return self._client.chat_json(system, user, validate=relaxed if validate else None, **kw)


# ------------------------------------------------------------------ the agents
class CAgents:
    """mode "mock": Person C's offline fixtures (no network, synthetic nutrition, recipes flagged mock).
    mode "live": the hackathon text gateway (needs TESSERACTED_BASE_URL / TESSERACTED_API_KEY) and the real Swiss nutrition CSV."""

    def __init__(self, mode: str = "mock", nutrition_csv: Path | None = None, servings: int = 4):
        if mode not in ("mock", "live"):
            raise ValueError("mode must be 'mock' or 'live'")
        config, llm, nutrition_agent, nutrition_db, recipe_agent, review_agent = _import_c()
        self.mode, self.servings, self.mock = mode, servings, mode == "mock"
        self._nutrition_agent, self._recipe_agent, self._review_agent = nutrition_agent, recipe_agent, review_agent
        if self.mock:
            cfg = config.Config(llm_provider="mock", offline=True)
        else:
            base, key = _env("TESSERACTED_BASE_URL"), _env("TESSERACTED_API_KEY")
            model = _env("EDITOR_LLM_MODEL")
            if not (base and key and model):
                raise CUnavailable("Live mode needs TESSERACTED_BASE_URL, TESSERACTED_API_KEY and EDITOR_LLM_MODEL (in the untracked .env).")
            cfg = config.Config(llm_provider="openai_compat", llm_base_url=base, llm_api_key=key, llm_model=model, review_model=model)
        self.cfg = cfg
        self.client = ImageChecksOff(llm.get_client(cfg))
        self.client_review = ImageChecksOff(llm.get_client(replace(cfg, llm_model=cfg.review_model or cfg.llm_model)))
        self.brand = recipe_agent.load_brand_rules(cfg)
        csv = Path(nutrition_csv) if nutrition_csv else (MOCK_NUTRITION_CSV if self.mock else REAL_NUTRITION_CSV)
        self.db = nutrition_db.NutritionDB.load(csv) if csv.is_file() else None
        self.synthetic = bool(self.db and self.db.is_fixture)
        self._iteration: dict[str, int] = {}
        self.last_reviews: list[dict] = []        # Person C's full review records, for the audit trail

    # --- generate -----------------------------------------------------------------------------
    def generate(self, proposal: dict, notes: str = "") -> dict:
        steering = [n.strip() for n in str(notes).splitlines() if n.strip()]
        recipes = self._recipe_agent.generate_recipes(self.client, proposal_to_c(proposal), steering, self.brand, [], self.servings)
        self._iteration = {}
        return {"proposal_id": proposal.get("id"), "steering_notes": str(notes).strip(), "recipes": [to_ours(r, self.mock) for r in recipes]}

    # --- review (soft + C's code-verified findings) -------------------------------------------
    def review(self, bundle: dict, notes: str = "") -> list[dict]:
        recipes = bundle["recipes"]

        def one(i: int):
            c = recipes[i]["_c"]
            sibling = recipes[1 - i]["_c"] if len(recipes) == 2 else None
            it = self._iteration[c["id"]] = self._iteration.get(c["id"], 0) + 1
            rv = self._review_agent.review_recipe(self.client_review, c, sibling, [], self.brand, it, "auto", None)   # no archive matches
            return i, rv

        if self.mock or len(recipes) < 2:                       # offline fixtures are replayed in a fixed order
            results = [one(i) for i in range(len(recipes))]
        else:                                                   # live: the two recipe reviews are independent, run them side by side
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(one, range(len(recipes))))
        findings: list[dict] = []
        for i, rv in sorted(results, key=lambda t: t[0]):
            self.last_reviews.append(rv)
            for f in findings_from_review(rv, i):
                if f["criterion"] == "differentiation" and any(g["criterion"] == "differentiation" for g in findings):
                    continue                                   # the two recipes are compared with each other: say it once
                findings.append(f)
        return findings

    # --- revise (open issues of the recipe and/or the editor's comment) -----------------------
    def revise(self, proposal: dict, notes: str, bundle: dict, issues: list[dict], comment: str = "") -> dict:
        """Automatic round (no comment): only recipes with HARD issues are revised, and their soft findings travel along; soft findings of
        other recipes stay visible for the editor. An editor comment is applied to both recipes."""
        steering = [n.strip() for n in str(notes).splitlines() if n.strip()]
        out = copy.deepcopy(bundle)
        has_hard = {x.get("recipe_index") for x in issues if x.get("kind") == "hard"}
        for i, r in enumerate(bundle["recipes"]):
            mine = [x for x in issues if x.get("recipe_index") in (i, None)]
            if not comment.strip() and not (i in has_hard or None in has_hard):
                continue
            if not mine and not comment.strip():
                continue
            report = "\n".join(f"{n}. [{x['criterion']}] {x['message']}" for n, x in enumerate(mine, 1)) or "(none)"
            try:
                new, _change_log = self._recipe_agent.revise_recipe(self.client, r["_c"], report, comment.strip() or None, steering)
            except Exception as exc:  # noqa: BLE001
                if self.mock and "no fixture" in str(exc):      # Person C's offline fixtures only cover some revisions: keep the recipe
                    continue
                raise
            out["recipes"][i] = to_ours(new, self.mock)
        return out

    # --- nutrition ----------------------------------------------------------------------------
    def nutrition(self, recipe: dict) -> dict:
        if self.db is None:
            return {"status": "pending", "per_serving": None, "assumptions": [], "synthetic": False, "unmatched": []}
        return nutrition_to_ours(self._nutrition_agent.compute_nutrition(recipe["_c"], self.db, self.client), self.synthetic)

    def agents(self, base: Agents | None = None) -> Agents:
        """Our Agents with generate/review/revise/nutrition replaced by Person C's; propose (and render) stay as given."""
        base = base or Agents()
        return Agents(propose=base.propose, generate=self.generate, review=self.review, revise=self.revise,
                      nutrition=self.nutrition, render=base.render)
