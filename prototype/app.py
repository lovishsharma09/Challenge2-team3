"""das schmeckt! Rezept-Werkstatt – one page, five steps, the whole flow live.

    ./run_prototype.sh            (http://localhost:8501)      ?mode=demo&step=4 replays the cached run
Signals -> Proposals -> Your decision -> Recipes (review + nutrition inside) -> Result.
"""
from __future__ import annotations

import sys
import time
import webbrowser
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prototype import adapters as ad                 # noqa: E402
from prototype import ui                             # noqa: E402
from prototype.export import PRINT_HELP, html_to_pdf, pdf_available  # noqa: E402
from prototype.ui import esc as h                    # noqa: E402
from editor.display import md, trail_label          # noqa: E402

st.set_page_config(page_title="das schmeckt! · Rezept-Werkstatt", page_icon=str(ui.LOGO) if ui.LOGO.is_file() else "🥬",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)

CRITERIA = {"title": "Title", "subheadings": "Sub-headings", "quantity_plausibility": "Quantities plausible",
            "quantity_completeness": "Quantities complete", "all_ingredients_used": "All ingredients used", "units_consistent": "Units",
            "tbsp_tsp": "EL / TL", "step_order": "Step order", "brand_fit": "Brand fit", "differentiation": "Differentiation",
            "culinary_plausibility": "Culinary logic", "food_safety": "Food safety", "completeness": "Completeness"}
AGENT_OF = {"selection": "Proposal Agent", "archive": "Archive Agent", "nutrition": "Nutrition Agent", "recipe": "Recipe Agent",
            "review": "Review Agent", "image": "Image Agent", "render": "Card layout", "editor": "Recipe Agent"}


# ----------------------------------------------------------------------------- state
def _init():
    ss = st.session_state
    ss.setdefault("step", 1); ss.setdefault("mode", "live"); ss.setdefault("run", None); ss.setdefault("error", None); ss.setdefault("pdfs", {})
    if not ss.get("_url_applied"):
        ss["_url_applied"] = True
        q = st.query_params
        if q.get("mode") == "demo" and ad.demo_available():
            ss["mode"], ss["run"], ss["tgl_demo"] = "demo", ad.load_run(ad.DEMO_DIR, "demo"), True
        if str(q.get("step", "")).isdigit():
            ss["step"] = max(1, min(5, int(q["step"])))


def _set_mode_from_toggle():
    ss = st.session_state
    if ss.get("tgl_demo"):
        if ad.demo_available():
            ss["mode"], ss["run"], ss["pdfs"] = "demo", ad.load_run(ad.DEMO_DIR, "demo"), {}
        else:
            ss["tgl_demo"], ss["error"] = False, "No demo cache yet: run the flow live once and save it as the demo cache."
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
        d.add(4)
        if run["c"].get("combined"):
            d.add(5)
    return d


def _reload():
    if st.session_state.get("run"):
        st.session_state["run"] = ad.load_run(st.session_state["run"]["dir"], st.session_state["mode"])


def _fail(title, exc):
    st.session_state["error"] = f"{title} – {type(exc).__name__}: {str(exc)[:300]}"


def _goto(step: int):
    st.session_state["step"], st.session_state["_sync_nav"] = step, True
    st.rerun()


def nav(can_next: bool):
    step = st.session_state["step"]
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    c1, c2, _ = st.columns([1, 3, 4])
    if step > 1 and c1.button("← Back", key=f"back_{step}", width="content"):
        _goto(step - 1)
    if step < 5 and c2.button(f"Next → {ui.STEPS[step]}", key=f"next_{step}", type="primary", disabled=not can_next, width="content"):
        _goto(step + 1)


class Timeline:
    """One compact agent timeline while a step runs: agent name, tick, seconds."""
    def __init__(self, status, label: str):
        self.status, self.label, self.ph, self.rows, self.t0 = status, label, status.empty(), {}, time.time()

    def mark(self, agent: str):
        now = time.time() - self.t0
        self.rows.setdefault(agent, [now, now])[1] = now
        self.status.update(label=f"{self.label} · {agent}…")
        self.render(current=agent)

    def render(self, current: str | None = None):
        names = list(self.rows)
        lines = []
        for i, a in enumerate(names):
            start = self.rows[a][0]
            end = self.rows[names[i + 1]][0] if i + 1 < len(names) else time.time() - self.t0
            lines.append(f"{'·' if a == current else '✓'} {h(a)} <span class='ds-muted'>{end - start:.1f} s</span>")
        self.ph.markdown("<br>".join(lines), unsafe_allow_html=True)

    def c_listener(self):
        return lambda stage, event, data: self.mark(AGENT_OF.get(stage, stage))

    def a_listener(self):
        def tell(msg: str):
            m = msg.lower()
            agent = ("Trend Agent" if "google" in m or "wikimedia" in m or "evidence" in m else
                     "Proposal Agent" if "pitch" in m else "Brand Agent / Archive Agent")
            self.mark(agent)
        return tell


_init()
ss = st.session_state
run, mode = ss["run"], ss["mode"]
demo = mode == "demo"
if ss.pop("_sync_nav", False) or "nav" not in ss:
    ss["nav"] = ss["step"]

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.toggle("Demo mode (cached run, no network)", key="tgl_demo", on_change=_set_mode_from_toggle)
    st.radio("Step", options=[1, 2, 3, 4, 5], format_func=lambda n: f"{n} · {ui.STEPS[n - 1]}", key="nav",
             on_change=lambda: ss.__setitem__("step", ss["nav"]))
    live = ad.c_live_available()
    st.caption("Services: " + " · ".join(f"{'●' if ok else '○'} {n}" for ok, n in ((live["llm"], "LLM"), (live["images"], "images"),
                                                                                 (live["nutrition_db"], "nutrition DB"), (live["archive"], "archive"))))
    if not demo:
        runs = ad.list_runs()
        if runs:
            choice = st.selectbox("Previous runs", ["(current)"] + [r.name for r in runs], key="replay")
            if choice != "(current)" and (not run or run["dir"].name != choice):
                ss["run"], ss["pdfs"] = ad.load_run(ad.RUNS_DIR / choice, "live"), {}
                st.rerun()
    if run and run.get("handoff"):
        for item in run["handoff"]["trail"]:
            st.caption(trail_label(item))
    if run and run.get("c") and not demo and st.button("Save as demo cache", key="btn_save_demo"):
        try:
            ad.save_demo_cache(run["dir"]); st.success("Saved.")
        except Exception as exc:  # noqa: BLE001
            _fail("Saving failed", exc)
    if st.button("Start over", key="btn_reset"):
        ss["run"], ss["step"], ss["error"], ss["pdfs"], ss["_sync_nav"] = (ad.load_run(ad.DEMO_DIR, "demo") if demo else None), 1, None, {}, True
        st.rerun()

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


# ----------------------------------------------------------------------------- 1 signals
def step_signals():
    st.markdown("## Signals")
    st.caption("Google Trends rising topics (DE, 18 Oct – 18 Nov 2026) and live Wikipedia pageviews. Missing evidence stays missing.")
    if not plist and not demo:
        if st.button("Run trend research", key="btn_run_a", type="primary", disabled=not ad.person_a_available()):
            run_dir = ad.new_run_dir()
            with st.status("Trend research", expanded=True) as status:
                tl = Timeline(status, "Trend research")
                try:
                    ad.run_person_a(run_dir, llm=True, progress=tl.a_listener())
                    tl.render(); status.update(label="Trend research done", state="complete", expanded=False)
                except Exception as exc:  # noqa: BLE001
                    status.update(label="Trend research failed", state="error"); _fail("Trend research could not finish", exc)
            ss["run"] = ad.load_run(run_dir, "live")
            st.rerun()
    left, right = st.columns([5, 6])
    in_top = {p["topic"] for p in plist}
    rows = [[r["topic"], r["search_interest"], r["increase"], ui.badge("shortlist", "ok") if r["topic"] in in_top else ""] for r in ad.rising_topics_table()]
    left.markdown(ui.card("<div class='ds-kicker'>Trend Agent · Google Trends</div>" + ui.table(["Topic", "Interest", "Increase", ""], rows, raw_cols={3})), unsafe_allow_html=True)
    if plist:
        rows = []
        for p in plist:
            s = ad.sparkline(p); w = (p.get("trend") or {}).get("wikimedia") or {}
            rows.append([f"#{p['rank']} {p.get('topic')}", ui.sparkline_svg([v for _, v in s]), f"{s[-1][1]:,}" if s else "–",
                         ui.badge(str(w.get("status", "–")).replace("_", " "), "ok" if w.get("status") == "available" else "warn")])
        right.markdown(ui.card("<div class='ds-kicker'>Trend Agent · Wikipedia pageviews, 14 days</div>" + ui.table(["Pitch", "", "Latest", "Status"], rows, raw_cols={1, 3})), unsafe_allow_html=True)
        t = run.get("timings", {}).get("person_a_seconds")
        right.caption(f"{len(plist)} proposals · {len(proposals.get('rejected_topics') or [])} rejected" + (f" · {t:.0f} s" if t else ""))
    nav(bool(plist))


# ----------------------------------------------------------------------------- 2 proposals
def step_proposals():
    st.markdown("## Proposals")
    st.caption("Ranked by trend 50 % · brand fit 30 % · archive novelty 20 %. Titles and ideas by the Proposal Agent from this evidence only.")
    if not plist:
        st.info("Run the trend research first."); nav(False); return
    for p in plist:
        t, b, a = p.get("trend") or {}, p.get("brand_fit") or {}, p.get("archive") or {}
        sim = [r for r in (a.get("similar_recipes") or []) if isinstance(r, dict)]
        badges = (ui.badge(f"trend {ui.fmt_num(t.get('score'))}", "neutral") + ui.badge(f"brand {ui.fmt_num(b.get('score'))}", "neutral")
                  + ui.badge(f"repetition {a.get('repetition_risk', '–')}", ui.risk_level(a.get("repetition_risk"))))
        ideas = "".join(f"<li>{h(i)}</li>" for i in (p.get("recipe_ideas") or [])[:2])
        arch = ("".join(f"<li>{h(r.get('title'))} <span class='ds-muted'>{h(r.get('published') or '')}</span></li>" for r in sim[:3])
                + (f"<li class='ds-muted'>+{len(sim) - 3} more</li>" if len(sim) > 3 else "")) if sim else "<li class='ds-muted'>no comparable archive recipe</li>"
        risks = "".join(f"<li>{h(r)}</li>" for r in (p.get("risks") or [])) or "<li class='ds-muted'>none from the evidence</li>"
        st.markdown(ui.card(
            f"<div class='ds-kicker'>#{p['rank']} · {h(p.get('topic'))}</div><h3>{h(p.get('title'))}</h3>{badges}"
            f"<p class='ds-muted' style='margin:8px 0'>{h(t.get('why_relevant'))}</p>"
            "<div style='display:flex;gap:32px;flex-wrap:wrap'>"
            f"<div style='flex:1;min-width:240px'><div class='ds-kicker'>Ideas</div><ul style='margin:4px 0 0 18px'>{ideas}</ul></div>"
            f"<div style='flex:1;min-width:240px'><div class='ds-kicker'>Archive</div><ul style='margin:4px 0 0 18px'>{arch}</ul></div>"
            f"<div style='flex:1;min-width:200px'><div class='ds-kicker'>Risks</div><ul style='margin:4px 0 0 18px'>{risks}</ul></div></div>"),
            unsafe_allow_html=True)
        with st.expander("Details"):
            from c_pipeline.recipe_agent import compact_proposal
            st.caption(h(b.get("reasoning") or ""))
            st.json(compact_proposal(p), expanded=False)
    with st.expander(f"Rejected topics ({len(proposals.get('rejected_topics') or [])})"):
        st.markdown(ui.table(["Topic", "Reason"], [[r.get("topic"), r.get("reason")] for r in proposals.get("rejected_topics") or []]), unsafe_allow_html=True)
    nav(True)


# ----------------------------------------------------------------------------- 3 decision
def step_decision():
    st.markdown("## Your decision")
    st.caption("One proposal and optional steering notes. The choice is audited and handed to the Recipe Agent.")
    if not plist:
        st.info("Run the trend research first."); nav(False); return
    sel = run.get("selection")
    ids = [p["id"] for p in plist]
    default = ids.index(sel["selected_ids"][0]) if sel and sel.get("selected_ids") and sel["selected_ids"][0] in ids else 0
    pick = st.radio("Proposal", ids, index=default, key="pick", disabled=bool(sel) or demo, format_func=lambda i: f"#{by_id[i]['rank']} · {by_id[i]['title']}")
    notes = st.text_area("Steering notes (one per line)", key="notes", disabled=bool(sel) or demo,
                         value="\n".join(sel.get("steering_notes", [])) if sel else "", placeholder="alltagstauglich, keine exotischen Zutaten")
    if not sel:
        if st.button("Hand off to the Recipe Agent", key="btn_handoff", type="primary", disabled=demo):
            try:
                ad.editor_handoff(run["dir"], pick, notes, selected_by="editor desk (prototype)"); _reload(); _goto(4)
            except Exception as exc:  # noqa: BLE001
                _fail("The handoff was rejected", exc); st.rerun()
    else:
        p = by_id.get(sel["selected_ids"][0], {})
        st.markdown(ui.card(f"<div class='ds-kicker'>Selected</div><h3>{h(p.get('title') or sel.get('selected_title'))}</h3>"
                            f"<div class='ds-muted'>Notes: {h(', '.join(sel.get('steering_notes') or []) or 'none')} · {h(sel.get('timestamp'))}</div>", soft=True), unsafe_allow_html=True)
        with st.expander("Details"):
            st.json({k: v for k, v in sel.items() if k != "batch_warnings"})
    nav(bool(sel))


# ----------------------------------------------------------------------------- 4 recipes
def run_c_button():
    if st.button("Generate the two recipes", key="btn_run_c", type="primary"):
        with st.status("Recipes", expanded=True) as status:
            tl = Timeline(status, "Recipes")
            try:
                ad.run_person_c(run["dir"], make_image=True, progress=tl.c_listener())
                tl.render(); status.update(label="Recipes done", state="complete", expanded=False)
            except Exception as exc:  # noqa: BLE001
                status.update(label="Recipe generation failed", state="error"); _fail("Recipe generation could not finish", exc)
        _reload(); st.rerun()
    st.caption("2–5 minutes: Recipe Agent, Review Agent (max 2 corrections), Image Agent, Nutrition Agent.")


def review_tab(rid: str, c: dict):
    recipe = next((r for r in c["recipes"] if r["id"] == rid), {})
    history = {hh.get("version"): hh for hh in recipe.get("history") or []}
    for rv in [x for x in c["review"] if x.get("recipe_id") == rid]:
        crit = {**(rv.get("criteria") or {}), **(rv.get("extras") or {})}
        failing = [(k, v) for k, v in crit.items() if not v.get("pass")]
        st.markdown(f"**Round {rv.get('iteration')}** · {rv.get('round_type')} · v{rv.get('recipe_version')} · "
                    + (":green[pass]" if rv.get("overall") == "pass" else f":red[revise] ({len(failing)})"))
        if rv.get("editor_comment"):
            st.caption("Editor: " + md(rv["editor_comment"]))
        for k, v in failing:
            issue = "; ".join(i for i in v.get("issues", []) if not str(i).startswith("Hinweis"))[:160]
            st.caption(f"{CRITERIA.get(k, k)}: {md(issue)} → {md(v.get('fix') or '')}")
        nxt = history.get((rv.get("recipe_version") or 0) + 1)
        if rv.get("overall") != "pass" and nxt:
            for ch in nxt.get("changes") or []:
                st.caption(f"fixed {md(ch.get('criterion'))}: {md(ch.get('change'))}")
        if not failing:
            st.caption(f"{len(crit)} criteria passed" + (" · LLM reviewer" if rv.get("llm_used") else " · code checks only"))
    with st.expander("Details"):
        st.json([x for x in c["review"] if x.get("recipe_id") == rid], expanded=False)


def nutrition_tab(rid: str, c: dict):
    n = (c.get("nutrition") or {}).get(rid)
    if not n:
        st.caption("No nutrition result."); return
    cov, ps = n.get("coverage") or {}, n.get("per_serving") or {}
    per = " · ".join(f"{label} {ui.fmt_num(ps.get(k), d)} {unit}" for k, label, unit, d in
                     (("kcal", "Energie", "kcal", 0), ("fat_g", "Fett", "g", 1), ("carbs_g", "Kohlenhydrate", "g", 1), ("protein_g", "Eiweiß", "g", 1), ("salt_g", "Salz", "g", 1))
                     if ps.get(k) is not None) or "no values (incomplete)"
    st.markdown(f"**Pro Portion:** {per} {ui.badge(cov.get('quality'), ui.quality_level(cov.get('quality')))}", unsafe_allow_html=True)
    rows = [[r.get("original"), f"{h(r.get('db_name'))}" + (" <span class='ds-muted'>(closest entry)</span>" if r.get("match") == "closest_category" else ""),
             ui.fmt_num(r.get("confidence"), 2)] for r in n.get("ingredients", [])]
    st.markdown(ui.table(["Ingredient", "Database match", "Confidence"], rows, raw_cols={1}), unsafe_allow_html=True)
    for u in n.get("unmatched", []):
        st.caption(f"not calculated: {u.get('original')}")
    st.caption(f"{cov.get('ingredients_calculated')} of {cov.get('ingredients_needing_calc')} ingredients matched · Schweizer Nährwertdatenbank {n.get('db', {}).get('version')}")
    with st.expander("Details"):
        st.json(n, expanded=False)


def recipe_tab(r: dict):
    from c_pipeline.render import ingredient_line
    times = r.get("times") or {}
    meta = f"{ui.fmt_num((r.get('servings') or {}).get('amount'))} {h((r.get('servings') or {}).get('unit', ''))}" + "".join(
        f" · {label} ca. {ui.fmt_num(times[k])} Min." for k, label in (("prep_min", "Vorbereitung"), ("cook_min", "Garzeit")) if times.get(k))
    ings = "".join(f"<li>{h(ingredient_line(i))}</li>" for i in r.get("ingredients", []))
    steps = "".join(f"<li>{h(s.get('text'))}</li>" for s in r.get("steps", []))
    st.markdown(f"<div class='ds-muted'>{meta}</div><p>{h(r.get('intro'))}</p><div class='ds-kicker'>Zutaten</div><ul style='margin:4px 0 10px 18px'>{ings}</ul>"
                f"<div class='ds-kicker'>Zubereitung</div><ol style='margin:4px 0 10px 18px'>{steps}</ol><div class='ds-kicker'>Unser Tipp</div><div>{h(r.get('serving_tip'))}</div>",
                unsafe_allow_html=True)
    used = ad.editor_rounds_used(run["dir"], r["id"])
    with st.expander(f"Send back ({2 - used} of 2 rounds left)"):
        comment = st.text_area("Comment", key=f"comment_{r['id']}", placeholder="weniger deftig, alltagstauglicher")
        if st.button("Send back and revise", key=f"btn_sendback_{r['id']}", disabled=demo or used >= 2) and not comment.strip():
            st.warning("Please write a comment first.")
        elif ss.get(f"btn_sendback_{r['id']}") and comment.strip():
            with st.status("Revision", expanded=True) as status:
                tl = Timeline(status, "Revision")
                try:
                    ad.send_back(run["dir"], r["id"], comment.strip(), make_image=True, progress=tl.c_listener())
                    tl.render(); status.update(label="Revision reviewed", state="complete", expanded=False)
                except Exception as exc:  # noqa: BLE001
                    status.update(label="Revision failed", state="error"); _fail("The revision failed", exc)
            _reload(); st.rerun()


def recipe_column(r: dict, c: dict):
    img = r.get("image") or {}
    v = img.get("verification")
    if img.get("resolved_path"):
        st.image(img["resolved_path"], width="stretch")
    vb = ui.badge(f"image {v.get('score')}/10", "ok" if (v.get("score") or 0) >= 7 else "warn") if isinstance(v, dict) else ui.badge("image unchecked", "warn")
    st.markdown(f"<div class='ds-kicker'>{h(r['id'])} · v{r.get('version', 1)} · review {h(r.get('review_status', '–'))}</div><h3>{h(r['title'])}</h3>{vb}", unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Recipe", "Review", "Nutrition"])
    with t1:
        recipe_tab(r)
    with t2:
        review_tab(r["id"], c)
    with t3:
        nutrition_tab(r["id"], c)


def step_recipes():
    st.markdown("## Recipes")
    if not run or not run.get("selection"):
        st.info("Make your decision first."); nav(False); return
    c = run.get("c")
    if not c:
        if demo:
            st.info("The cached run has no recipes.")
        else:
            run_c_button()
        nav(False); return
    st.caption("Two drafts for the chosen pitch; each reviewed against the 8 criteria, photographed and calculated per serving.")
    for col, r in zip(st.columns(2, gap="large"), c["recipes"]):
        with col:
            recipe_column(r, c)
    nav(True)


# ----------------------------------------------------------------------------- 5 result
def step_result():
    st.markdown("## Result")
    c = (run or {}).get("c")
    if not c:
        st.info("Generate the recipes first."); nav(False); return
    m = ad.impact_metrics(c, run.get("timings"))
    pages = {rid: ad.page_count(p) for rid, p in c["cards"].items()}
    secs = (m.get("person_a_seconds") or 0) + (m.get("person_c_seconds") or 0)
    matched = sum(x.get("matched") or 0 for x in m["nutrition"].values()); of = sum(x.get("of") or 0 for x in m["nutrition"].values())
    strip = [(f"{secs:.0f} s" if secs else "–", "measured, end to end"), (m["issues_caught"], "issues caught by the Review Agent"),
             (f"{matched} / {of}", "ingredients matched in the database"), (" / ".join(str(p) for p in pages.values()) or "–", "pages per card")]
    for col, (v, label) in zip(st.columns(4), strip):
        col.markdown(ui.metric(v, label), unsafe_allow_html=True)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    for col, r in zip(st.columns(2, gap="large"), c["recipes"]):
        with col:
            path = c["cards"].get(r["id"])
            if not path:
                continue
            html = Path(path).read_text(encoding="utf-8")
            b1, b2, b3 = st.columns([1, 1.6, 1.6])
            if b1.button("Open", key=f"open_{r['id']}", width="content"):
                webbrowser.open(Path(path).resolve().as_uri())
            b2.download_button("Download HTML", html, file_name=f"{r['id']}.html", mime="text/html", key=f"dl_html_{r['id']}", width="content")
            if pdf_available():
                if r["id"] not in ss["pdfs"]:
                    if b3.button("Prepare PDF", key=f"btn_pdf_{r['id']}", width="content"):
                        with st.spinner("Rendering A4 PDF…"):
                            ss["pdfs"][r["id"]] = html_to_pdf(path)
                        st.rerun()
                elif ss["pdfs"][r["id"]]:
                    b3.download_button("Download PDF", ss["pdfs"][r["id"]], file_name=f"{r['id']}.pdf", mime="application/pdf", key=f"dl_pdf_{r['id']}", width="content")
            preview = html.replace("</head>", "<style>.toolbar,.print-help{display:none!important}body{zoom:.76;margin:0;background:#fcfbf7}</style></head>", 1)
            st.iframe(preview, height=int(1123 * 0.76 * max(1, pages.get(r["id"]) or 1)) + 24, width="stretch")
    if not pdf_available():
        st.caption(PRINT_HELP)
    nav(False)


{1: step_signals, 2: step_proposals, 3: step_decision, 4: step_recipes, 5: step_result}[step]()
