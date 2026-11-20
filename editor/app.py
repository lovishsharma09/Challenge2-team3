"""Editor desk (Person B). Run from the repo root:  streamlit run editor/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit.components.v1 as components

from editor import llm
from editor.agents import Agents, propose_with_archive, propose_with_trends
from editor.archive import configured_archive
from editor.c_agents import CAgents, CUnavailable
from editor.batch import BatchError, is_template_angle, load_batch, propose_from_batch
from editor.display import coverage_short, evidence_details, highlight_change, md, pitch_fields, short, trail_label
from editor.llm_agents import with_llm
from editor.render import ingredient_text
from editor.workflow import EditorWorkflow, WorkflowError

st.set_page_config(page_title="Editor Desk · das schmeckt!", layout="wide")

SOURCE_BATCH = "Saved proposal batch (local JSON)"
SOURCE_FALLBACK = "Offline candidate ranking (fallback, not Person A's pitches)"
ENGINE_BUILTIN = "Built-in mock samples (default)"
ENGINE_C_MOCK = "Person C pipeline · offline mock (no network)"
ENGINE_C_LIVE = "Person C pipeline · live text gateway (sends text)"


@st.cache_resource(show_spinner="Loading Person C's pipeline and the nutrition database…")
def c_engine(mode: str) -> CAgents:
    return CAgents("live" if mode == ENGINE_C_LIVE else "mock")


@st.cache_resource(show_spinner="Reading the local trend data and recipe archive…")
def fallback_agents() -> tuple[Agents, list[str]]:
    """Opt-in fallback: offline candidate ranking from the provided data. No brand fit, no recipe angles (not invented)."""
    trends_dir = llm._env("EDITOR_TRENDS_DIR") or str(Path(__file__).resolve().parent.parent / "data" / "trends")
    try:
        real = propose_with_trends(trends_dir, configured_archive())
        return Agents(propose=real), list(real.notes)
    except (OSError, ValueError, KeyError) as exc:
        return Agents(propose=propose_with_archive(configured_archive())), [f"Trend data not usable ({exc}); proposals are MOCK."]


with st.sidebar:
    st.header("Proposal source")
    source = st.radio("Source", [SOURCE_BATCH, SOURCE_FALLBACK], key="source",
                      help="Person A supplies the five ranked pitches. The fallback is only for when no batch exists and is labelled as such.")
    st.header("Recipe engine")
    engine = st.radio("Engine", [ENGINE_BUILTIN, ENGINE_C_MOCK, ENGINE_C_LIVE], key="engine",
                      help="Who writes, reviews and calculates the two drafts. The live engine sends the pitch and recipe text to the hackathon "
                           "text gateway (never archive titles) and uses no image generation.")
    batch_path = ""
    if source == SOURCE_BATCH:
        batch_path = st.text_input("Batch file (local JSON, stays on this machine)", value=llm._env("EDITOR_PROPOSALS_JSON"), key="batch_path")
        reload_batch = st.button("Reload batch file")
    else:
        reload_batch = False

batch, batch_errors, agents, data_notes = None, [], None, []
if source == SOURCE_BATCH:
    try:
        batch = load_batch(batch_path)
        agents = Agents(propose=propose_from_batch(batch))
    except BatchError as exc:
        batch_errors = exc.messages
else:
    agents, data_notes = fallback_agents()

engine_error = ""
if agents is not None and engine != ENGINE_BUILTIN:
    try:
        agents = c_engine(engine).agents(agents)
    except CUnavailable as exc:
        engine_error = str(exc)
        agents = None
if engine_error:
    with st.sidebar:
        st.error(engine_error)

source_key = (source, batch_path if source == SOURCE_BATCH else "", engine)
if reload_batch or st.session_state.get("source_key") != source_key:     # a different source starts a clean workflow
    st.session_state.wf = EditorWorkflow(agents or Agents())
    st.session_state.source_key = source_key
    st.session_state.pop("pick", None)
    st.session_state.pop("error", None)
wf: EditorWorkflow = st.session_state.wf


def act(fn, *args):
    """Run a workflow action; show a clear error instead of a stack trace."""
    with st.status("Working…", expanded=True) as status:
        wf.on_progress = lambda message: status.write(message)
        try:
            fn(*args)
        except WorkflowError as exc:
            st.session_state.error = str(exc)
            status.update(label="Failed", state="error")
        else:
            st.session_state.pop("error", None)
            status.update(label="Done", state="complete")
        finally:
            wf.on_progress = lambda message: None
    st.rerun()


st.title("Editor Desk · das schmeckt!")
st.caption("The system prepares the decision. The editor decides. Recipe generation, nutrition and images are still stubs; "
           "German texts from the archive and the recipe cards stay in German.")
current = {"idle": "start", "proposals": "proposals", "review": "review", "approved": "approved"}[wf.stage]
st.markdown(" → ".join(f"**{s}**" if s == current else s for s in ("start", "proposals", "review", "approved")))
if "error" in st.session_state:
    st.error(st.session_state.error)

with st.sidebar:
    st.header("Decision trail")
    for item in wf.trail:
        st.caption(trail_label(item))
    if engine != ENGINE_BUILTIN:
        st.caption("Review, revision and nutrition come from Person C's pipeline.")
    elif llm.configured():
        use_llm = st.checkbox("Real LLM for review and revision (Tesseracted)", value=False,
                              help="Sends the recipe text to the hackathon gateway. Off = mock agents.")
        wf.agents = with_llm(wf.agents) if use_llm else Agents(propose=wf.agents.propose, generate=wf.agents.generate,
                                                                 nutrition=wf.agents.nutrition)
    else:
        st.caption("Real LLM: not configured (no .env).")
    if st.button("Reset"):
        wf.reset()
        st.rerun()

if wf.stage == "idle":
    if engine_error:
        st.error("The chosen recipe engine cannot be used, and nothing was replaced by mock data: " + engine_error)
    if batch_errors:
        st.error("The Person A batch cannot be used. Nothing was replaced by mock data:\n\n" + "\n".join(f"- {m}" for m in batch_errors))
        st.info("Fix the file or the path, then press 'Reload batch file'. If no batch exists yet, you can switch the source in the sidebar "
                "to the offline candidate ranking; it is labelled as a fallback and does not invent brand fit or recipe angles.")
    elif source == SOURCE_BATCH:
        st.success(batch.source_label)
    if st.button("Load the five pitches" if source == SOURCE_BATCH else "Run the offline candidate ranking",
                 type="primary", disabled=bool(batch_errors) or bool(engine_error)):
        act(wf.start)


def show_change(c: dict):
    """One concrete correction: where, and the sentence before and after with the difference marked."""
    st.markdown(f"**{md(c['recipe_title'])} · {md(c['where'])}**")
    if c["before"] is not None and c["after"] is not None:
        old, new = highlight_change(c["before"], c["after"])
    else:
        old = md(c["before"]) if c["before"] is not None else "_(nothing)_"
        new = f":green[**{md(c['after'])}**]" if c["after"] is not None else "_(removed)_"
    st.markdown("Before: " + old)
    st.markdown("After: " + new)


def pitch_card(p: dict, picked: str | None, noun: str):
    """One choice: title, one recipe angle, one short 'Why now' sentence, a Choose button. Brand reasoning, archive matches, scores
    and original labels are under 'View evidence'. Every supplied text goes through md(): it comes from a file and must never
    format the page or load external images."""
    f = pitch_fields(p)
    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(f"### #{md(p['rank'])} · {md(p['title'])}")
            if noun == "pitch":
                st.markdown("**Recipe angle:** " + (md(f["angle"]) if f["angle"] else "_none supplied_")
                            + (" ⚠️ _placeholder_" if is_template_angle(f["angle"]) else ""))
            else:
                st.caption("No recipe angle yet: the offline ranking does not invent one.")
            st.markdown("**Why now:** " + (md(short(f["why_now"], 180)) if f["why_now"] else "_none supplied_"))
        with right:
            if picked == p["id"]:
                st.success("Selected")
            elif st.button(f"Choose this {noun}", key=f"pick-{p['id']}", type="primary" if picked is None else "secondary"):
                st.session_state.pick = p["id"]
                st.rerun()
        with st.expander("View evidence"):
            e = evidence_details(p)
            if noun == "pitch":
                st.markdown("**Brand fit:** " + (md(e["brand_full"]) if e["brand_full"] else "_not assessed_"))
            else:
                st.markdown("**Brand fit:** _not assessed: the offline ranking does not apply the brand guidelines._")
            if e["why_full"] and short(e["why_full"], 180) != e["why_full"]:
                st.markdown("**Why now (full):** " + md(e["why_full"]))
            for extra in e["more_angles"]:
                st.markdown("**Further recipe idea:** " + md(extra))
            st.markdown(e["coverage_full"])
            if e["team_changes"] or e["original"]:
                st.markdown("**Team draft: what changed against Person A's original**")
                for c in e["team_changes"]:
                    st.markdown(f"- {c}")
                for k, label in (("title", "Title"), ("angle", "Recipe angle"), ("why_now", "Why now"), ("brand_reason", "Brand fit")):
                    if e["original"].get(k):
                        st.caption(f"Original {label}: {e['original'][k]}")
            st.divider()
            st.markdown(e["ranked"])
            if e["rank_method"]:
                st.caption(e["rank_method"])
            if e["source_terms"]:
                st.markdown(e["source_terms"])
            st.markdown(e["sources"])
            if e["trend_summary"]:
                st.caption(e["trend_summary"])
            st.markdown(e["wikipedia"])
            st.caption(e["trend_line"])
            st.write("Brand fit as supplied:")
            st.json(p["brand_fit"], expanded=False)
            st.caption(e["archive_line"])
            if e["dates_line"]:
                st.caption(e["dates_line"])


def batch_notice(proposals: list[dict]):
    """ONE compact notice for everything worth knowing about the batch; the details are one click away."""
    notes: list[str] = []
    if source == SOURCE_BATCH and batch is not None:
        notes += batch.warnings
        unchecked = sum(coverage_short(p)[0] == "warn" for p in proposals)
        if unchecked:
            notes.append(f"Prior coverage could not be checked for {unchecked} of {len(proposals)} pitches (archive not available), "
                         "so 'no match' cannot be told apart from 'not checked' there.")
        extra = f" · {len(notes)} note{'s' if len(notes) != 1 else ''}" if notes else ""
        if batch.draft_label:
            st.warning(f"**{md(batch.draft_label)}** · {md(batch.draft_status)}{extra}")
        else:
            st.info(f"**Person A saved batch** · {len(proposals)} pitches in A's order{extra}")
        with st.expander("Batch details" + (f" and {len(notes)} note{'s' if len(notes) != 1 else ''}" if notes else "")):
            st.caption(md(batch.source_label))
            if batch.draft_label:
                st.markdown("This is a team draft, not Person A's approved batch."
                            + (f" Based on Person A's {md(batch.based_on)}." if batch.based_on else "")
                            + " The changes against the original are listed under 'View evidence' on every pitch.")
            st.markdown("The ranking is shown as supplied; it is not recalculated here.")
            for n_ in notes:
                st.markdown(f"- {md(n_)}")
    else:
        extra = f" · {len(data_notes)} note{'s' if len(data_notes) != 1 else ''}" if data_notes else ""
        st.warning(f"**Offline candidate ranking** (a fallback, not Person A's pitches){extra}")
        with st.expander("Details" + (f" and {len(data_notes)} note{'s' if len(data_notes) != 1 else ''}" if data_notes else "")):
            st.markdown("Brand fit and recipe angles are not assessed or invented here.")
            for n_ in data_notes:
                st.markdown(f"- {md(n_)}")


if wf.stage == "proposals":
    fixed = not wf.can_reject_all()
    noun = "pitch" if source == SOURCE_BATCH else "topic"
    picked = st.session_state.get("pick")
    if picked not in {p["id"] for p in wf.proposals}:
        picked = None
    batch_notice(wf.proposals)
    for p in wf.proposals:
        pitch_card(p, picked, noun)
    notes = st.text_area("Steering notes (optional)", placeholder="e.g. weeknight-friendly, less dairy")
    c1, c2 = st.columns(2)
    if c1.button("Generate two recipes", type="primary", disabled=picked is None,
                 help=None if picked else "Choose a pitch first."):
        act(wf.select, picked, notes)
    if fixed:
        c2.caption("These pitches are a fixed batch, so 'none of these fit' is not available: "
                   "no replacement batch or rerun exists. Load a different batch instead.")
    else:
        reject_note = c2.text_input("None fit? Optional note", key="reject_note")
        if c2.button("None of these fit: propose other topics"):
            act(wf.reject_all, reject_note)
    with st.expander("Considered and rejected topics"):
        for r in wf.rejected:
            st.markdown(f"- **{md(r['topic'])}**: {md(r['reason'])}")


def review_history():
    """The full history in ONE collapsed expander (Streamlit cannot nest expanders, so rounds are headed sections)."""
    with st.expander(f"Review history ({len(wf.rounds)} round{'s' if len(wf.rounds) != 1 else ''})"):
        for rnd in wf.rounds:
            n_open = sum(1 for i in rnd["issues"] if i["status"] == "open")
            st.markdown(f"**Round {rnd['round']}** · {n_open} open issue(s), {len(rnd['fixed'])} fixed since last round")
            for i in rnd["issues"]:
                st.write(f"{i['kind'].upper()} · {i['criterion']} · {i['message']}")
            for i in rnd["fixed"]:
                st.write(f"🟢 fixed: {i['message']}")
            if rnd.get("changes"):
                st.markdown("Changes made in this round:")
                for c in rnd["changes"]:
                    show_change(c)
            st.divider()


if wf.stage in ("review", "approved"):
    if wf.stage == "review":
        ok, why = wf.can_approve()
        soft_open = [i for i in wf.issues if i["status"] == "open" and i["kind"] == "soft"]
        if ok:
            st.success("**Ready to approve.** No blocking issues" + (f"; {len(soft_open)} soft warning(s) stay visible and do not block." if soft_open else "."))
        else:
            st.error("**Blocked.** " + why)
    st.info(f"Selected: **{wf.selected['title']}** · steering notes: {wf.notes or 'none'}")
    mock = any(r.get("mock") for r in wf.bundle["recipes"])
    if mock:
        st.warning(("Mock drafts: fixed sample recipes (lentil soup) used to rehearse the review and export flow. " if engine == ENGINE_BUILTIN else
                    "Mock drafts: Person C's offline fixtures, used to rehearse the review and export flow. ")
                   + "They are NOT generated from the selected pitch and are not real results.")
    st.subheader("Recipes")
    for r in wf.bundle["recipes"]:
        with st.expander(f"{r['title']} · {'Mock draft' if r.get('mock') else 'AI-generated draft'}", expanded=wf.stage == "review"):
            st.markdown(md(r.get("subtitle", "")))
            left, right = st.columns([1, 2])
            left.markdown("**Ingredients**\n\n" + "\n".join(f"- {md(ingredient_text(i))}" for i in r["ingredients"]))
            right.markdown("**Steps**\n\n" + "\n".join(f"{n}. {md(step)}" for n, step in enumerate(r["steps"], 1)))

    if wf.stage == "review":
        for notice in wf.notices:
            st.warning(notice)
        open_issues = [i for i in wf.issues if i["status"] == "open"]
        for i in (x for x in open_issues if x["kind"] == "hard"):
            with st.container(border=True):
                st.write(f"🛑 HARD (blocks approval, cannot be dismissed) · {i['criterion']}")
                st.write(i["message"])
        soft_open = [x for x in open_issues if x["kind"] == "soft"]
        if soft_open:
            with st.expander(f"{len(soft_open)} soft warning{'s' if len(soft_open) != 1 else ''} (do not block approval)"):
                for n, i in enumerate(soft_open):
                    st.markdown(f"⚠️ **{md(i['criterion'])}**: {md(i['message'])}")
                    reason = st.text_input("Note for the record (optional: acknowledge this warning)", key=f"reason{n}")
                    if st.button("Acknowledge warning", key=f"ack{n}"):
                        act(wf.acknowledge, i["key"], reason)
                    st.divider()
        for i in (x for x in wf.issues if x["status"] == "dismissed"):
            st.caption(f"⚪ acknowledged: {i['message']} — {i['dismiss_reason']}")

        st.subheader("Your decision")
        last = wf.rounds[-1] if wf.rounds else None
        correction, controls = st.columns([3, 2])
        with correction:                                   # one concrete before/after, right next to the decision controls
            st.markdown("**Latest correction**")
            changes = (last or {}).get("changes") or []
            if last and last["round"] > 1 and changes:
                show_change(next((c for c in changes if c["where"].startswith(("Step", "Ingredient"))), changes[0]))     # a real fix beats wording
                if len(changes) > 1:
                    st.caption(f"+{len(changes) - 1} more change(s) in the review history below.")
            elif last and last["round"] > 1:
                st.caption("The last revision did not change the recipe text" + (", so the open hard issues above remain." if not ok else "."))
            else:
                st.caption("No revision yet: the drafts are shown as first generated.")
        with controls:
            comment = st.text_area("Comment for the recipe agent (needed to send back)")
            b1, b2 = st.columns(2)
            if b1.button("Approve both recipes", type="primary", disabled=not ok, help=why or None):
                act(wf.approve)
            if b2.button(f"Send back ({wf.editor_rounds_left()} left)", disabled=wf.editor_rounds_left() <= 0):
                act(wf.send_back, comment)
        with st.expander("Not happy with these recipes at all?"):
            why_discard = st.text_input("Reason (optional)", key="discard_reason")
            if st.button("Discard these recipes and choose another proposal"):
                act(wf.discard, why_discard)
    else:
        st.success("Approved. The two recipe cards were exported" + (" (mock drafts):" if any(r.get("mock") for r in wf.bundle["recipes"]) else ":"))
        tabs = st.tabs([f"Card {n}: {r['title']}" for n, r in enumerate(wf.bundle["recipes"], 1)])
        for n, (tab, path) in enumerate(zip(tabs, wf.result["cards"]), 1):
            with tab:
                page = Path(path).read_text(encoding="utf-8")
                st.download_button("Download this card (HTML, print to PDF from the browser)", page, file_name=Path(path).name,
                                   mime="text/html", key=f"download-{n}")
                st.caption(f"Saved locally as {md(path)}")
                components.html(page, height=1400, scrolling=True)
        warnings = wf.result["approved_with_warnings"]
        if warnings:
            st.warning("Approved with open or dismissed issues:\n\n" +
                       "\n".join(f"- [{w['status']}] {w['message']} {w['dismiss_reason']}" for w in warnings))
        for item in wf.result["nutrition"]:
            n = item["nutrition"]
            if n["status"] == "pending":
                gaps = f" Not calculated: {md(', '.join(str(u) for u in n.get('unmatched', [])))}." if n.get("unmatched") else ""
                st.write(f"**{md(item['recipe_title'])}**: nutrition pending (no value is invented)." + gaps)
                continue
            ps = n["per_serving"]
            head = " · ".join(f"{label} {ps[k]}" for k, label in (("kcal", "kcal"), ("fat_g", "fat g"), ("carbs_g", "carbs g"), ("protein_g", "protein g"))
                              if ps.get(k) is not None)
            st.write(f"**{md(item['recipe_title'])}**: per serving {head}" + (" · **SYNTHETIC test data, not real values**" if n.get("synthetic") else ""))
            if n.get("coverage_text"):
                st.caption(md(n["coverage_text"]))
            if n.get("assumptions") or n.get("unmatched"):
                with st.expander(f"Nutrition assumptions and gaps: {item['recipe_title']}"):
                    for a in n.get("assumptions", []):
                        st.markdown(f"- {md(a.get('original'))} → {md(a.get('used'))} (confidence {md(a.get('confidence'))})")
                    for u in n.get("unmatched", []):
                        st.markdown(f"- **not calculated:** {md(u)}")
    review_history()
