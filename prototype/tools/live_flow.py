"""Drive the real page through the whole LIVE flow with Streamlit's AppTest (no browser): the same buttons a user clicks.

    python prototype/tools/live_flow.py [--pick <proposal id>] [--notes "..."] [--save-demo]

Prints what each step produced and exits non-zero if a step failed. Needs the keys in person_c/.env.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prototype import adapters as ad  # noqa: E402


def texts(at) -> str:
    return "\n".join(m.value for m in at.markdown) + "\n" + "\n".join(c.value for c in at.caption)


def must(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", default="")
    ap.add_argument("--notes", default="alltagstauglich, keine exotischen Zutaten")
    ap.add_argument("--save-demo", action="store_true")
    a = ap.parse_args()
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "prototype" / "app.py"), default_timeout=1800)
    at.run()
    must(not at.exception, f"page error: {at.exception}")

    t0 = time.time()
    print("step 1: run Person A …")
    at.button(key="btn_run_a").click().run()
    must(not at.exception, f"step 1 error: {at.exception}")
    must(not at.session_state["error"], f"step 1 reported: {at.session_state['error']}")
    run = at.session_state["run"]
    props = run["proposals"]["proposals"]
    print(f"  {len(props)} proposals in {time.time() - t0:.0f}s, schema {run['proposals'].get('_schema')}")
    for p in props:
        print(f"  #{p['rank']} {p['id']} | {p['title']} | text {p.get('text_source')} | ideas: {p['recipe_ideas'][:2]}")
    print("  run dir:", run["dir"])

    print("step 3: editor choice …")
    at.radio(key="nav").set_value(3).run()
    pick = a.pick or props[0]["id"]
    at.radio(key="pick").set_value(pick).run()
    at.text_area(key="notes").set_value(a.notes).run()
    at.button(key="btn_handoff").click().run()
    must(not at.exception, f"step 3 error: {at.exception}")
    must(not at.session_state["error"], f"step 3 reported: {at.session_state['error']}")
    run = at.session_state["run"]
    print("  selection.json:", {k: run["selection"][k] for k in ("picks", "selected_ids", "steering_notes", "selected_by")})
    must(at.session_state["step"] == 4, "did not advance to step 4")

    print("step 4: run Person C (this takes minutes) …")
    t1 = time.time()
    at.button(key="btn_run_c").click().run()
    must(not at.exception, f"step 4 error: {at.exception}")
    must(not at.session_state["error"], f"step 4 reported: {at.session_state['error']}")
    run = at.session_state["run"]
    c = run["c"]
    print(f"  Person C finished in {time.time() - t1:.0f}s")
    for r in c["recipes"]:
        v = (r.get("image") or {}).get("verification")
        n = c["nutrition"].get(r["id"], {})
        print(f"  {r['id']} v{r.get('version')} | {r['title']} | kcal {n.get('per_serving', {}).get('kcal')} ({n.get('coverage', {}).get('quality')}) "
              f"| image {r.get('image', {}).get('status')} score {v.get('score') if isinstance(v, dict) else v} | pages {ad.page_count(c['cards'].get(r['id']))}")
    print("  review rounds:", [(x['recipe_id'], x['iteration'], x['overall']) for x in c["review"]])
    txt = texts(at)
    must("Zutaten" in txt, "step 4 does not show the recipes")

    for n in (5, 6):
        at.radio(key="nav").set_value(n).run()
        must(not at.exception, f"step {n} error: {at.exception}")
    txt = texts(at)
    must("Seconds per stage" in txt, "step 6 impact panel missing")
    print("step 5/6 rendered. downloads:", [b.label for b in at.get("download_button")])

    if a.save_demo:
        at.radio(key="nav").set_value(6).run()
        at.button(key="btn_save_demo").click().run()
        must(not at.exception, f"save demo error: {at.exception}")
        must(not at.session_state["error"], f"save demo reported: {at.session_state['error']}")
        print("demo cache saved:", ad.DEMO_DIR, "files:", len([p for p in ad.DEMO_DIR.rglob('*') if p.is_file()]))
    print(f"ALL STEPS OK in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
