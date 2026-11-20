"""das schmeckt! Rezept-Werkstatt – ONE page that runs the whole flow live.

    ./run_prototype.sh            (http://localhost:8501)

Steps: 1 Trend evidence (A) -> 2 Five proposals (A) -> 3 Editor choice (B, writes selection.json) ->
4 Recipes (C) -> 5 Review & nutrition (C) -> 6 Cards & impact.  Sidebar: live / demo (cached run), previous runs.
URL parameters for demos and screenshots: ?mode=demo&step=4
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prototype import adapters as ad                 # noqa: E402
from prototype import ui                             # noqa: E402
from prototype.export import PRINT_HELP, html_to_pdf, pdf_available  # noqa: E402
from editor.display import md, trail_label          # noqa: E402  (Person B's markdown escaping + decision-trail wording)
from prototype.ui import esc as h                    # noqa: E402  (HTML escaping for the HTML blocks)

st.set_page_config(page_title="das schmeckt! · Rezept-Werkstatt", page_icon=str(ui.LOGO) if ui.LOGO.is_file() else "🥬",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)

CRITERIA_LABELS = {"title": "Title", "subheadings": "Sub-headings", "quantity_plausibility": "Quantities plausible",
                   "quantity_completeness": "Quantities complete", "all_ingredients_used": "All ingredients used",
                   "units_consistent": "Units consistent", "tbsp_tsp": "EL / TL correct", "step_order": "Step order",
                   "brand_fit": "Brand fit", "differentiation": "Differentiation", "culinary_plausibility": "Culinary logic",
                   "food_safety": "Food safety", "completeness": "Completeness"}
NUTRIENTS = [("kcal", "Energie", "kcal", 0), ("kj", "Energie", "kJ", 0), ("fat_g", "Fett", "g", 1), ("sat_fat_g", "davon gesättigt", "g", 1),
             ("carbs_g", "Kohlenhydrate", "g", 1), ("sugar_g", "davon Zucker", "g", 1), ("fiber_g", "Ballaststoffe", "g", 1),
             ("protein_g", "Eiweiß", "g", 1), ("salt_g", "Salz", "g", 1)]


# ----------------------------------------------------------------------------- state
def _init():
    ss = st.session_state
    ss.setdefault("step", 1)
    ss.setdefault("mode", "live")
    ss.setdefault("run", None)
    ss.setdefault("error", None)
    ss.setdefault("pdfs", {})
    if not ss.get("_url_applied"):
        ss["_url_applied"] = True
        q = st.query_params
        if q.get("mode") == "demo" and ad.demo_available():
            ss["mode"], ss["run"] = "demo", ad.load_run(ad.DEMO_DIR, "demo")
            ss["tgl_demo"] = True
        if str(q.get("step", "")).isdigit():
            ss["step"] = max(1, min(6, int(q["step"])))


def _set_mode_from_toggle():
    ss = st.session_state
    if ss.get("tgl_demo"):
        if ad.demo_available():
            ss["mode"], ss["run"], ss["pdfs"] = "demo", ad.load_run(ad.DEMO_DIR, "demo"), {}
        else:
            ss["tgl_demo"] = False
            ss["error"] = "No demo cache yet: run the flow live once and press 'Save this run as the demo cache'."
    else:
        ss["mode"], ss["run"], ss["step"], ss["pdfs"] = "live", None, 1, {}
    ss["_sync_nav"] = True


def _done(run) -> set[int]:
    d = set()
    if run and run.get("proposals"):
        d |= {1, 2}
    if run and run.get("selection"):
        d.add(3)
    if run and run.get("c"):
        d |= {4, 5}
        if run["c"].get("combined"):
            d.add(6)
    return d


def _reload():
    ss = st.session_state
    if ss.get("run"):
        ss["run"] = ad.load_run(ss["run"]["dir"], ss["mode"])


def _fail(title: str, exc: Exception):
    st.session_state["error"] = f"{title} – {type(exc).__name__}: {str(exc)[:400]}"


def _goto(step: int):
    """Change the step from a button: the sidebar radio already exists in this run, so it is synced at the start of the next one."""
    st.session_state["step"] = step
    st.session_state["_sync_nav"] = True
    st.rerun()


def nav_buttons(can_next: bool, next_label: str = "Next →"):
    step = st.session_state["step"]
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    c1, c2, _ = st.columns([1, 1, 6])
    if step > 1 and c1.button("← Back", key=f"back_{step}"):
        _goto(step - 1)
    if step < 6 and c2.button(next_label, key=f"next_{step}", type="primary", disabled=not can_next):
        _goto(step + 1)


_init()
ss = st.session_state
run = ss["run"]
mode = ss["mode"]
demo = mode == "demo"
if ss.pop("_sync_nav", False) or "nav" not in ss:       # before the radio is instantiated (Streamlit rule)
    ss["nav"] = ss["step"]

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### Rezept-Werkstatt")
    st.toggle("Demo mode (replay a cached live run, no network)", key="tgl_demo", on_change=_set_mode_from_toggle,
              help="Live mode is the default. The demo replays one real run that was saved from this page.")
    st.radio("Go to step", options=[1, 2, 3, 4, 5, 6], format_func=lambda n: f"{n} · {ui.STEPS[n - 1]}", key="nav",
             on_change=lambda: ss.__setitem__("step", ss["nav"]))
    live = ad.c_live_available()
    st.markdown("**Live services**")
    for ok, label in ((live["llm"], "LLM gateway (Tesseracted)"), (live["images"], "FLUX images (Black Forest Labs)"),
                      (live["nutrition_db"], "Swiss nutrition database"), (live["archive"], "5,000-recipe archive export")):
        st.caption(("🟢 " if ok else "⚪ ") + label)
    if not demo:
        runs = ad.list_runs()
        if runs:
            choice = st.selectbox("Replay a previous live run", ["(current)"] + [r.name for r in runs], key="replay")
            if choice != "(current)" and (not run or run["dir"].name != choice):
                ss["run"], ss["pdfs"] = ad.load_run(ad.RUNS_DIR / choice, "live"), {}
                st.rerun()
    if run and run.get("handoff"):
        st.markdown("**Editor decision trail**")
        for item in run["handoff"]["trail"]:
            st.caption("• " + trail_label(item))
    if run and run.get("c") and not demo:
        if st.button("Save this run as the demo cache", key="btn_save_demo", help="Copies the JSON, cards and images into prototype/demo_cache (no keys)."):
            try:
                ad.save_demo_cache(run["dir"])
                st.success("Saved to prototype/demo_cache.")
            except Exception as exc:  # noqa: BLE001
                _fail("Saving the demo cache failed", exc)
    if st.button("Start over", key="btn_reset"):
        ss["run"], ss["step"], ss["error"], ss["pdfs"] = (ad.load_run(ad.DEMO_DIR, "demo") if demo else None), 1, None, {}
        ss["_sync_nav"] = True
        st.rerun()
    if run:
        st.caption(f"Run folder: {md(str(run['dir'].relative_to(ROOT)) if str(run['dir']).startswith(str(ROOT)) else str(run['dir']))}")

# ----------------------------------------------------------------------------- header
st.markdown(ui.top_bar(mode), unsafe_allow_html=True)
step = ss["step"]
st.markdown(ui.stepper(step, _done(run)), unsafe_allow_html=True)
if ss.get("error"):
    c1, c2 = st.columns([8, 1])
    c1.error(ss["error"])
    if c2.button("Dismiss", key="btn_dismiss"):
        ss["error"] = None
        st.rerun()

proposals = (run or {}).get("proposals") or {}
plist = proposals.get("proposals") or []
by_id = {p["id"]: p for p in plist}


# ----------------------------------------------------------------------------- step 1: trend evidence
def step_trend():
    st.markdown("## 1 · Trend evidence <span class='ds-kicker'>Person A</span>", unsafe_allow_html=True)
    st.markdown("<div class='ds-muted'>Rising Google Trends topics for Germany (18 Oct – 18 Nov 2026) are checked against German Wikipedia "
                "pageviews, scored for brand fit and compared with the recipe archive. Nothing here is invented: missing evidence stays missing.</div>",
                unsafe_allow_html=True)
    if not plist:
        if demo:
            st.info("Demo mode: no cached proposals found.")
        else:
            st.markdown("")
            if st.button("Run Person A now (live: Wikimedia, archive, LLM titles)", key="btn_run_a", type="primary", disabled=not ad.person_a_available()):
                run_dir = ad.new_run_dir()
                with st.status("Person A · trend research running…", expanded=True) as status:
                    try:
                        ad.run_person_a(run_dir, llm=True, progress=lambda m: status.write("· " + m))
                        status.update(label="Person A finished", state="complete", expanded=False)
                    except Exception as exc:  # noqa: BLE001
                        status.update(label="Person A failed", state="error")
                        _fail("Person A could not finish", exc)
                ss["run"], ss["error"] = ad.load_run(run_dir, "live"), ss.get("error")
                st.rerun()
            st.caption("Takes about 30–60 seconds (live Wikipedia pageviews for 12 topics, 5,000 archive recipes, LLM pitch texts).")
    left, right = st.columns([5, 6])
    with left:
        rows = ad.rising_topics_table()
        in_top = {p["topic"] for p in plist}
        body = [[r["topic"], r["search_interest"], r["increase"], ui.badge("in top 5", "ok") if r["topic"] in in_top else ""] for r in rows]
        st.markdown(ui.card("<div class='ds-kicker'>Google Trends · rising topics (DE)</div>"
                            + ui.table(["Topic", "Search interest 0-100", "Increase", "Shortlist"], body, raw_cols={3})
                            + "<div class='ds-muted' style='margin-top:8px'>Source file: searched_with_rising-searches_topics_DE_20261018-1818_20261118-1818.csv · "
                              "the index is relative within the export, not a search volume.</div>"), unsafe_allow_html=True)
    with right:
        if plist:
            body = []
            for p in plist:
                series = ad.sparkline(p)
                w = (p.get("trend") or {}).get("wikimedia") or {}
                status = w.get("status", "–")
                lvl = "ok" if status == "available" else "warn"
                body.append([f"#{p['rank']} {p.get('topic')}", ui.sparkline_svg([v for _, v in series]),
                             f"{series[-1][1]:,}" if series else "–", ui.badge(status, lvl), ui.fmt_num(w.get("score"))])
            st.markdown(ui.card("<div class='ds-kicker'>Wikipedia pageviews · last 14 days</div>"
                                + ui.table(["Pitch", "14-day sparkline", "Latest day", "Status", "Change score"], body, raw_cols={1, 3})
                                + "<div class='ds-muted' style='margin-top:8px'>Live Wikimedia REST pageviews for the German article; "
                                  "'no_article_found' means the signal could not be checked.</div>"), unsafe_allow_html=True)
            t = run.get("timings", {}).get("person_a_seconds")
            meta = f"{len(plist)} proposals · {len(proposals.get('rejected_topics') or [])} rejected · schema {h(proposals.get('_schema', '?'))}"
            if t:
                meta += f" · measured {t:.0f} s"
            st.markdown(f"<div class='ds-muted'>{meta}</div>", unsafe_allow_html=True)
        else:
            st.markdown(ui.card("<div class='ds-kicker'>Wikipedia pageviews</div><div class='ds-muted'>Appears after Person A ran.</div>", soft=True),
                        unsafe_allow_html=True)
    nav_buttons(bool(plist), "Next → Five proposals")


# ----------------------------------------------------------------------------- step 2: five proposals
def proposal_card(p: dict):
    t, b, a = p.get("trend") or {}, p.get("brand_fit") or {}, p.get("archive") or {}
    g = ad.google_signal(p)
    sim = [r for r in (a.get("similar_recipes") or []) if isinstance(r, dict)]
    head = (f"<div class='ds-kicker'>#{p['rank']} · rank score {ui.fmt_num(p.get('rank_score'), 1)} · topic: {h(p.get('topic'))}"
            + (" · <span class='ds-badge ds-neutral'>template text</span>" if p.get("text_source", "template") == "template" else "") + "</div>"
            f"<h3>{h(p.get('title'))}</h3>")
    badges = (ui.badge(f"Google interest {ui.fmt_num(t.get('score'))}/100 · {g['increase'] or '–'}", "neutral")
              + ui.badge(f"brand fit {ui.fmt_num(b.get('score'))}/100 · {b.get('fit', '–')}", {"high": "ok", "medium": "warn", "low": "bad"}.get(b.get("fit"), "neutral"))
              + ui.badge(f"repetition risk {a.get('repetition_risk', '–')}", ui.risk_level(a.get("repetition_risk")))
              + ui.badge(str(a.get('match_status', '–')).replace('_', ' '), "neutral"))
    ideas = "".join(f"<li>{h(i)}</li>" for i in (p.get("recipe_ideas") or [])[:2])
    risks = "".join(f"<li>{h(r)}</li>" for r in (p.get("risks") or [])) or "<li class='ds-muted'>none from the evidence</li>"
    sim_rows = [[r.get("title"), r.get("published") or "–", r.get("date_source") or "", r.get("match_level") or ""] for r in sim[:5]]
    sim_html = (ui.table(["Similar archive recipe", "Date", "Date source", "Match"], sim_rows)
                + (f"<div class='ds-muted'>{len(sim)} matches in the export, latest {h(a.get('most_recent_comparable_publication') or '–')} "
                   "(CMS dates, not verified publication dates)</div>" if sim else "")) if sim else "<div class='ds-muted'>No comparable recipe found in the export.</div>"
    series = ad.sparkline(p)
    html = (head + badges +
            f"<p style='margin:10px 0 6px 0'><b>Why now:</b> {h(t.get('why_relevant'))}</p>"
            "<div style='display:flex;gap:28px;flex-wrap:wrap'>"
            f"<div style='flex:1;min-width:260px'><div class='ds-kicker'>Recipe ideas</div><ul style='margin:4px 0 0 18px'>{ideas}</ul>"
            f"<div class='ds-kicker' style='margin-top:10px'>Brand fit</div><div class='ds-muted'>{h(b.get('reasoning'))}</div></div>"
            f"<div style='flex:1.4;min-width:320px'><div class='ds-kicker'>Archive check</div>{sim_html}"
            f"<div style='margin-top:6px'><b>Content gap:</b> {h(a.get('content_gap') or '–')}</div></div>"
            f"<div style='flex:0.8;min-width:200px'><div class='ds-kicker'>Risks</div><ul style='margin:4px 0 0 18px'>{risks}</ul>"
            f"<div class='ds-kicker' style='margin-top:10px'>Wikipedia 14 days</div>{ui.sparkline_svg([v for _, v in series])}</div>"
            "</div>")
    st.markdown(ui.card(html), unsafe_allow_html=True)
    with st.expander(f"Evidence as supplied by Person A (#{p['rank']})"):
        from c_pipeline.recipe_agent import compact_proposal
        st.json(compact_proposal(p), expanded=False)


def step_proposals():
    st.markdown("## 2 · Five proposals <span class='ds-kicker'>Person A → editor</span>", unsafe_allow_html=True)
    if not plist:
        st.info("Run Person A in step 1 first.")
        nav_buttons(False)
        return
    st.markdown("<div class='ds-muted'>Ranked 50 % Google Trends + 30 % brand fit + 20 % archive novelty (deterministic). Titles and recipe ideas "
                "are written by the LLM from this evidence only; the original template texts stay in the file.</div>", unsafe_allow_html=True)
    for p in plist:
        proposal_card(p)
    rej = proposals.get("rejected_topics") or []
    with st.expander(f"Considered and rejected topics ({len(rej)})"):
        st.markdown(ui.table(["Topic", "Reason", "Rank score"], [[r.get("topic"), r.get("reason"), ui.fmt_num(r.get("rank_score"), 1)] for r in rej]),
                    unsafe_allow_html=True)
    nav_buttons(True, "Next → Editor choice")


# ----------------------------------------------------------------------------- step 3: editor choice
def step_choice():
    st.markdown("## 3 · Editor choice <span class='ds-kicker'>Person B · editor desk</span>", unsafe_allow_html=True)
    if not plist:
        st.info("Run Person A in step 1 first.")
        nav_buttons(False)
        return
    sel = run.get("selection")
    st.markdown("<div class='ds-muted'>The system prepares the decision, the editor decides: one pitch, optional steering notes. "
                "The choice is written to Person B's audit log and handed to Person C as <code>selection.json</code>.</div>", unsafe_allow_html=True)
    ids = [p["id"] for p in plist]
    default = ids.index(sel["selected_ids"][0]) if sel and sel.get("selected_ids") and sel["selected_ids"][0] in ids else 0
    pick = st.radio("Choose one proposal", ids, index=default, key="pick", disabled=bool(sel) or demo,
                    format_func=lambda i: f"#{by_id[i]['rank']} · {by_id[i]['title']}")
    notes = st.text_area("Steering notes for the recipe agent (one per line, optional)", key="notes", disabled=bool(sel) or demo,
                         value="\n".join(sel.get("steering_notes", [])) if sel else "", placeholder="e.g. alltagstauglich, keine exotischen Zutaten")
    if not sel:
        if st.button("Hand off to Person C (write selection.json)", key="btn_handoff", type="primary", disabled=demo):
            try:
                ad.editor_handoff(run["dir"], pick, notes, selected_by="editor desk (prototype)")
                _reload()
                _goto(4)
            except Exception as exc:  # noqa: BLE001
                _fail("The editor desk rejected the batch", exc)
                st.rerun()
    else:
        p = by_id.get(sel["selected_ids"][0], {})
        st.markdown(ui.card(f"<div class='ds-kicker'>Selected</div><h3>{h(p.get('title') or sel.get('selected_title'))}</h3>"
                            f"<div><b>Steering notes:</b> {h(', '.join(sel.get('steering_notes') or []) or 'none')}</div>"
                            f"<div class='ds-muted'>selected_by {h(sel.get('selected_by'))} · {h(sel.get('timestamp'))} · picks {sel.get('picks')}</div>", soft=True),
                    unsafe_allow_html=True)
        for w in sel.get("batch_warnings") or []:
            st.warning(w)
        with st.expander("selection.json (Person C contract)"):
            st.json({k: v for k, v in sel.items() if k != "batch_warnings"})
    nav_buttons(bool(sel), "Next → Recipes")


# ----------------------------------------------------------------------------- step 4: recipes
def _progress_status(status):
    labels = {"selection": "Reading the editor's selection", "archive": "Loading the recipe archive", "nutrition": "Nutrition",
              "recipe": "Recipe Agent", "review": "Review Agent", "image": "Images (FLUX + vision check)", "render": "Rendering the A4 cards",
              "editor": "Editor round"}

    def on_event(stage, event, data):
        status.update(label=f"Person C · {labels.get(stage, stage)}…")
        status.write(f"· [{stage}] {event}")
    return on_event


def run_c_button():
    live = ad.c_live_available()
    if not live["llm"]:
        st.warning("No LLM gateway configured (person_c/.env): Person C would run with mock recipes.")
    if not live["images"]:
        st.caption("No image key: cards get a placeholder instead of a FLUX photo.")
    if st.button("Generate the two recipes (Person C live: recipes → review loop → images → nutrition → cards)", key="btn_run_c", type="primary"):
        with st.status("Person C · starting…", expanded=True) as status:
            try:
                ad.run_person_c(run["dir"], make_image=True, progress=_progress_status(status))
                status.update(label="Person C finished", state="complete", expanded=False)
            except Exception as exc:  # noqa: BLE001
                status.update(label="Person C failed", state="error")
                _fail("Person C could not finish", exc)
        _reload()
        st.rerun()
    st.caption("Takes 2–5 minutes: two recipes, up to 2 review corrections each, two FLUX images with a vision check, nutrition per serving.")


def recipe_column(r: dict, c: dict):
    img = r.get("image") or {}
    v = img.get("verification")
    path = img.get("resolved_path")
    if path:
        st.image(path, width="stretch")
    else:
        st.markdown(ui.card("<div class='ds-muted'>No image (placeholder on the card).</div>", soft=True), unsafe_allow_html=True)
    vb = (ui.badge(f"image check {v.get('score')}/10" + (" · retried" if v.get("retried") else ""), "ok" if (v.get("score") or 0) >= 7 else "warn")
          if isinstance(v, dict) else ui.badge("image check not available", "warn"))
    times = r.get("times") or {}
    meta = f"{ui.fmt_num((r.get('servings') or {}).get('amount'))} {h((r.get('servings') or {}).get('unit', ''))}"
    for k, label in (("prep_min", "Vorbereitung"), ("cook_min", "Garzeit"), ("rest_min", "Ruhezeit")):
        if times.get(k):
            meta += f" · {label} ca. {ui.fmt_num(times[k])} Min."
    st.markdown(f"<div class='ds-kicker'>{h(r['id'])} · version {r.get('version', 1)} · review {h(r.get('review_status', '–'))}</div>"
                f"<h3>{h(r['title'])}</h3>{vb}<div class='ds-muted' style='margin:6px 0'>{meta}</div>"
                f"<p>{h(r.get('intro'))}</p>", unsafe_allow_html=True)
    from c_pipeline.render import ingredient_line
    ings = "".join(f"<li>{h(ingredient_line(i))}</li>" for i in r.get("ingredients", []))
    steps = "".join(f"<li>{h(s.get('text'))}</li>" for s in r.get("steps", []))
    st.markdown(f"<div class='ds-kicker'>Zutaten</div><ul style='margin:4px 0 10px 18px'>{ings}</ul>"
                f"<div class='ds-kicker'>Zubereitung</div><ol style='margin:4px 0 10px 18px'>{steps}</ol>"
                f"<div class='ds-kicker'>Unser Tipp</div><div>{h(r.get('serving_tip'))}</div>", unsafe_allow_html=True)
    used = ad.editor_rounds_used(run["dir"], r["id"])
    with st.expander(f"Send back to the Recipe Agent ({2 - used} of 2 editor rounds left)"):
        comment = st.text_area("Your comment (required)", key=f"comment_{r['id']}", placeholder="e.g. weniger deftig, alltagstauglicher")
        if st.button("Send back and revise", key=f"btn_sendback_{r['id']}", disabled=demo or used >= 2 or not comment.strip()):
            with st.status(f"Person C · editor round for {r['id']}…", expanded=True) as status:
                try:
                    ad.send_back(run["dir"], r["id"], comment.strip(), make_image=True, progress=_progress_status(status))
                    status.update(label="Revision reviewed", state="complete", expanded=False)
                except Exception as exc:  # noqa: BLE001
                    status.update(label="Editor round failed", state="error")
                    _fail("The editor round failed", exc)
            _reload()
            st.rerun()
        if demo:
            st.caption("Not available in demo mode (needs the live LLM).")


def step_recipes():
    st.markdown("## 4 · Recipes <span class='ds-kicker'>Person C · Recipe Agent</span>", unsafe_allow_html=True)
    if not run or not run.get("selection"):
        st.info("Hand off a selection in step 3 first.")
        nav_buttons(False)
        return
    c = run.get("c")
    if not c:
        if demo:
            st.info("Demo cache has no Person C output.")
        else:
            run_c_button()
        nav_buttons(False)
        return
    st.markdown("<div class='ds-muted'>Two differentiated drafts for the chosen pitch, written in the magazine's infinitive style, "
                "each reviewed against the 8 criteria (max 2 automatic corrections) and photographed by FLUX with a vision check.</div>",
                unsafe_allow_html=True)
    cols = st.columns(2, gap="large")
    for col, r in zip(cols, c["recipes"]):
        with col:
            recipe_column(r, c)
    if not demo:
        with st.expander("Run Person C again for this selection"):
            run_c_button()
    nav_buttons(True, "Next → Review & nutrition")


# ----------------------------------------------------------------------------- step 5: review & nutrition
def review_panel(rid: str, c: dict):
    rounds = [rv for rv in c["review"] if rv.get("recipe_id") == rid]
    recipe = next((r for r in c["recipes"] if r["id"] == rid), {})
    history = {h.get("version"): h for h in recipe.get("history") or []}
    st.markdown(f"<div class='ds-kicker'>Review rounds · {len(rounds)}</div>", unsafe_allow_html=True)
    for rv in rounds:
        crit, extras = rv.get("criteria") or {}, rv.get("extras") or {}
        failing = [k for k, v in {**crit, **extras}.items() if not v.get("pass")]
        head = (f"Round {rv.get('iteration')} · {rv.get('round_type')} · recipe v{rv.get('recipe_version')} · "
                f"{'PASS' if rv.get('overall') == 'pass' else 'REVISE'} ({len(failing)} failing)")
        with st.expander(head, expanded=rv is rounds[-1]):
            if rv.get("editor_comment"):
                st.markdown(f"**Editor comment:** {md(rv['editor_comment'])}")
            rows = []
            for k in list(crit) + list(extras):
                v = crit.get(k) or extras.get(k) or {}
                issues = "<br>".join(h(i) for i in v.get("issues", [])) or "<span class='ds-muted'>–</span>"
                rows.append([CRITERIA_LABELS.get(k, k) + ("" if k in crit else " (extra)"), ui.badge("pass" if v.get("pass") else "fail", "ok" if v.get("pass") else "bad"),
                             issues, v.get("fix") or ""])
            st.markdown(ui.table(["Criterion", "Result", "Issues found", "Correction asked"], rows, raw_cols={1, 2}), unsafe_allow_html=True)
            st.caption(("LLM reviewer used" if rv.get("llm_used") else "Code checks only (LLM unavailable)") +
                       (f" · archive matches compared: {len(rv.get('archive_matches') or [])}"))
            nxt = history.get((rv.get("recipe_version") or 0) + 1)
            if rv.get("overall") != "pass" and nxt:
                st.markdown(f"**Corrections made → v{nxt['version']}**")
                for ch in nxt.get("changes") or []:
                    st.markdown(f"- `{md(ch.get('criterion'))}` {md(ch.get('change'))}")
            if rv.get("archive_matches"):
                st.markdown("**Similar archive recipes checked for differentiation**")
                st.markdown(ui.table(["Title", "Modified", "Similarity"], [[m.get("title"), m.get("modified"), ui.fmt_num(m.get("similarity"), 2)]
                                                                            for m in rv["archive_matches"][:5]]), unsafe_allow_html=True)


def nutrition_panel(rid: str, c: dict):
    n = (c.get("nutrition") or {}).get(rid)
    if not n:
        st.info("No nutrition result for this recipe.")
        return
    cov, ps = n.get("coverage") or {}, n.get("per_serving") or {}
    q = cov.get("quality")
    st.markdown(f"<div class='ds-kicker'>Nutrition per serving · {ui.badge('quality ' + str(q), ui.quality_level(q))} "
                f"{ui.badge(str(cov.get('ingredients_calculated')) + ' of ' + str(cov.get('ingredients_needing_calc')) + ' ingredients matched', 'neutral')} "
                f"{ui.badge('mean confidence ' + ui.fmt_num(cov.get('mean_confidence'), 2), 'neutral')}</div>", unsafe_allow_html=True)
    cols = st.columns(len(NUTRIENTS))
    for col, (k, label, unit, d) in zip(cols, NUTRIENTS):
        col.markdown(ui.metric(f"{ui.fmt_num(ps.get(k), d)} {unit}" if ps.get(k) is not None else "–", label), unsafe_allow_html=True)
    rows = []
    for row in n.get("ingredients", []):
        lvl = {"exact": "ok", "closest": "warn", "llm": "warn", "alias": "warn", "closest_category": "bad"}.get(row.get("match"), "neutral")
        rows.append([row.get("original"), f"{h(row.get('db_name'))} <span class='ds-muted'>#{h(row.get('db_id'))}</span>",
                     ui.fmt_num(row.get("grams"), 1), row.get("conversion"), ui.badge("assumption", "warn") if row.get("assumption") else "",
                     ui.fmt_num(row.get("confidence"), 2), ui.badge(row.get("match"), lvl), ui.fmt_num(row.get("kcal"), 0)])
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown(ui.table(["Ingredient", "Database entry", "Grams", "Conversion", "", "Confidence", "Match", "kcal"], rows, raw_cols={1, 4, 6}),
                unsafe_allow_html=True)
    for u in n.get("unmatched", []):
        st.warning(f"Not calculated: {u.get('original')} – {u.get('reason')}")
    for note in n.get("notes", []):
        st.caption("• " + note)
    st.caption(f"Database: {n.get('db', {}).get('source')} · version {n.get('db', {}).get('version')} · reference {n.get('reference')} · "
               f"{n.get('servings')} servings")


def image_panel(rid: str, c: dict):
    r = next((x for x in c["recipes"] if x["id"] == rid), {})
    img = r.get("image") or {}
    v = img.get("verification")
    if not isinstance(v, dict):
        st.markdown(ui.badge("image verification: " + str(v or "n/a"), "warn"), unsafe_allow_html=True)
        return
    st.markdown(f"<div class='ds-kicker'>Image verification</div>"
                f"{ui.badge(f'score {v.get('score')}/10 (min {v.get('min_score')})', 'ok' if (v.get('score') or 0) >= 7 else 'warn')} "
                f"{ui.badge('retried' if v.get('retried') else 'no retry needed', 'neutral')} "
                f"{ui.badge('foods not in recipe: ' + (', '.join(v.get('foods_not_in_recipe') or []) or 'none'), 'ok' if not v.get('foods_not_in_recipe') else 'bad')} "
                f"{ui.badge('missing: ' + (', '.join(v.get('missing_components') or []) or 'none'), 'ok' if not v.get('missing_components') else 'warn')}",
                unsafe_allow_html=True)
    st.caption(f"Vision model: {v.get('model')} · components checked: {', '.join(v.get('components') or [])}")
    with st.expander("Image prompt and attempts"):
        st.markdown(f"**Prompt:** {md(r.get('image_prompt'))}")
        for a in v.get("attempts") or []:
            st.markdown(f"- attempt {a.get('attempt')}: score {a.get('score')} · visible: {md(', '.join(a.get('visible_foods') or []))}")


def step_review():
    st.markdown("## 5 · Review & nutrition <span class='ds-kicker'>Person C · Review Agent, Nutrition Agent</span>", unsafe_allow_html=True)
    c = (run or {}).get("c")
    if not c:
        st.info("Generate the recipes in step 4 first.")
        nav_buttons(False)
        return
    tabs = st.tabs([f"{r['id']} · {r['title']}" for r in c["recipes"]])
    for tab, r in zip(tabs, c["recipes"]):
        with tab:
            review_panel(r["id"], c)
            st.divider()
            nutrition_panel(r["id"], c)
            st.divider()
            image_panel(r["id"], c)
    nav_buttons(True, "Next → Cards & impact")


# ----------------------------------------------------------------------------- step 6: cards & impact
def step_cards():
    st.markdown("## 6 · Cards & impact <span class='ds-kicker'>A4 recipe cards · measured numbers</span>", unsafe_allow_html=True)
    c = (run or {}).get("c")
    if not c:
        st.info("Generate the recipes in step 4 first.")
        nav_buttons(False)
        return
    m = ad.impact_metrics(c, run.get("timings"))
    cols = st.columns(6)
    pages = {rid: ad.page_count(p) for rid, p in c["cards"].items()}
    tiles = [(f"{m['person_a_seconds']:.0f} s" if m.get("person_a_seconds") else "–", "Person A · trend → proposals"),
             (f"{m['person_c_seconds']:.0f} s" if m.get("person_c_seconds") else "–", "Person C · recipes → cards"),
             (m["review_rounds"], "review rounds"), (m["issues_caught"], "issues caught"), (m["corrections"], "corrections made"),
             (" / ".join(str(p) for p in pages.values()) or "–", "pages per card")]
    for col, (v, label) in zip(cols, tiles):
        col.markdown(ui.metric(v, label), unsafe_allow_html=True)
    left, right = st.columns([1, 1])
    with left:
        rows = [[stage, f"{secs:.1f}"] for stage, secs in m["seconds_per_stage"].items()]
        st.markdown(ui.card("<div class='ds-kicker'>Seconds per stage (stage_c_log.json)</div>" + ui.table(["Stage", "Seconds"], rows)), unsafe_allow_html=True)
    with right:
        rows = []
        for rid, nm in m["nutrition"].items():
            sc = m["image_scores"].get(rid, {})
            rows.append([rid, f"{nm.get('matched')}/{nm.get('of')} ({ui.fmt_num((nm.get('share') or 0) * 100)} %)", ui.badge(nm.get("quality"), ui.quality_level(nm.get("quality"))),
                         str(nm.get("closest")), f"{sc.get('score', '–')}/10" if sc.get("score") is not None else "n/a"])
        st.markdown(ui.card("<div class='ds-kicker'>Nutrition match rate · image check</div>"
                            + ui.table(["Recipe", "Ingredients matched", "Quality", "Closest-entry assumptions", "Image score"], rows, raw_cols={2})),
                    unsafe_allow_html=True)
    st.markdown("### The cards")
    names = [r["id"] for r in c["recipes"] if r["id"] in c["cards"]]
    tabs = st.tabs([f"{rid} · {next(r['title'] for r in c['recipes'] if r['id'] == rid)} · {pages.get(rid)} page(s)" for rid in names] + ["Both cards"])
    for tab, rid in zip(tabs, names):
        with tab:
            html = Path(c["cards"][rid]).read_text(encoding="utf-8")
            b1, b2, _ = st.columns([1.2, 1.2, 4])
            b1.download_button("Download HTML", html, file_name=f"{rid}.html", mime="text/html", key=f"dl_html_{rid}")
            if pdf_available():
                if rid not in ss["pdfs"]:
                    if b2.button("Prepare PDF", key=f"btn_pdf_{rid}"):
                        with st.spinner("Rendering A4 PDF…"):
                            ss["pdfs"][rid] = html_to_pdf(c["cards"][rid])
                        st.rerun()
                elif ss["pdfs"][rid]:
                    b2.download_button("Download PDF", ss["pdfs"][rid], file_name=f"{rid}.pdf", mime="application/pdf", key=f"dl_pdf_{rid}")
                else:
                    b2.caption("PDF rendering failed – use the browser's print dialog.")
            else:
                b2.caption(PRINT_HELP)
            st.iframe(html, height=1180 * max(1, pages.get(rid) or 1) + 80, width="stretch")
    with tabs[-1]:
        if c.get("combined"):
            html = Path(c["combined"]).read_text(encoding="utf-8")
            st.download_button("Download both cards (HTML)", html, file_name="das_schmeckt_rezepte.html", mime="text/html", key="dl_html_both")
            st.iframe(html, height=1180 * max(1, sum(pages.values())) + 80, width="stretch")
    nav_buttons(False)


{1: step_trend, 2: step_proposals, 3: step_choice, 4: step_recipes, 5: step_review, 6: step_cards}[step]()
