"""Demo pre-flight: is everything in place? Run from the repo root:  .venv/bin/python -m editor.preflight [--live]

Checks (no secrets are printed): dependencies, Person C's package, the proposal batch, the real nutrition database, the gateway settings,
the offline engine end to end, and (with --live) one tiny call to the text gateway with its latency. Exit code 0 = READY.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from . import llm
from .llm import _env

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BATCH = REPO / "data" / "local" / "proposals-review-draft.json"


def check_dependencies():
    import requests  # noqa: F401
    import streamlit  # noqa: F401
    return "streamlit and requests import"


def check_person_c():
    from .c_agents import _import_c
    _import_c()
    return "Person C's package imports"


def check_batch():
    from .batch import load_batch
    path = _env("EDITOR_PROPOSALS_JSON") or str(DEFAULT_BATCH)
    b = load_batch(path)
    kind = b.draft_label or "Person A saved batch"
    return f"{kind}: {len(b.proposals)} pitches ({Path(path).name}), {len(b.warnings)} batch note(s)"


def check_nutrition_db():
    from .c_agents import REAL_NUTRITION_CSV, _import_c
    _, _, _, nutrition_db, _, _ = _import_c()
    db = nutrition_db.NutritionDB.load(REAL_NUTRITION_CSV)
    if db.is_fixture or len(db.entries) < 1000:
        raise RuntimeError(f"unexpected database ({len(db.entries)} entries, fixture={db.is_fixture})")
    return f"real Swiss nutrition database, {len(db.entries)} entries"


def check_gateway_settings():
    missing = [k for k in ("TESSERACTED_BASE_URL", "TESSERACTED_API_KEY", "EDITOR_LLM_MODEL") if not _env(k)]
    if missing:
        raise RuntimeError("missing in .env: " + ", ".join(missing))
    return f"gateway settings present, model {_env('EDITOR_LLM_MODEL').split('/')[-1]}"


def check_offline_engine():
    from .agents import Agents
    from .batch import load_batch, propose_from_batch
    from .c_agents import CAgents
    from .workflow import EditorWorkflow
    batch = load_batch(_env("EDITOR_PROPOSALS_JSON") or str(DEFAULT_BATCH))
    with tempfile.TemporaryDirectory() as d:
        wf = EditorWorkflow(CAgents("mock").agents(Agents(propose=propose_from_batch(batch))), Path(d) / "a.jsonl", Path(d) / "cards")
        wf.start()
        wf.select(wf.proposals[0]["id"], "")
        if not wf.can_approve()[0]:
            raise RuntimeError("the offline rehearsal run did not reach 'Ready to approve'")
        wf.approve()
        if len(wf.result["cards"]) != 2:
            raise RuntimeError("the offline run did not export two cards")
    return "offline engine: choose, review, correct, approve, two cards"


def check_gateway_live():
    t = time.time()
    out = llm.chat_json("Reply with JSON only.", 'Reply exactly {"ok": true}', timeout=60)
    if out.get("ok") is not True:
        raise RuntimeError(f"unexpected reply: {out}")
    return f"gateway answers in {time.time() - t:.1f} s"


def run(live: bool = False) -> int:
    checks = [("dependencies", check_dependencies), ("Person C", check_person_c), ("proposal batch", check_batch),
              ("nutrition database", check_nutrition_db), ("gateway settings", check_gateway_settings),
              ("offline engine", check_offline_engine)]
    if live:
        checks.append(("live gateway", check_gateway_live))
    failures = 0
    for name, fn in checks:
        try:
            print(f"  OK    {name}: {fn()}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {str(exc)[:200]}")
    print("\n" + ("READY" if not failures else f"NOT READY ({failures} problem(s))") +
          ("" if live else "   (add --live to test the gateway)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run("--live" in sys.argv))
