"""Editor desk (Person B). Run from the repo root:  streamlit run editor/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from editor import llm
from editor.agents import Agents
from editor.display import archive_summary, wikimedia_summary
from editor.llm_agents import with_llm
from editor.workflow import EditorWorkflow, WorkflowError

st.set_page_config(page_title="Editor Desk · das schmeckt!", layout="wide")
if "wf" not in st.session_state:
    st.session_state.wf = EditorWorkflow()
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
st.caption("The system prepares the decision. The editor decides. (Agents are mock stubs for now.)")
current = {"idle": "start", "proposals": "proposals", "review": "review", "approved": "approved"}[wf.stage]
st.markdown(" → ".join(f"**{s}**" if s == current else s for s in ("start", "proposals", "review", "approved")))
if "error" in st.session_state:
    st.error(st.session_state.error)

with st.sidebar:
    st.header("Decision trail")
    for item in wf.trail:
        detail = {k: v for k, v in item.items() if k != "event"}
        st.caption(f"**{item['event']}** {detail if detail else ''}")
    if llm.configured():
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
    if st.button("Run trend research", type="primary"):
        act(wf.start)

if wf.stage == "proposals":
    st.subheader("Qualified proposals")
    for p in wf.proposals:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            with left:
                st.markdown(f"### #{p['rank']} · {p['title']}")
                st.write(p["trend"]["why_relevant"])
                st.caption(p["brand_fit"]["reasoning"])
                for level, text in (wikimedia_summary(p), archive_summary(p)):
                    (st.warning if level == "warn" else st.write)(text)
            with right:
                st.metric("Trend", p["trend"]["score"])
                st.metric("Brand fit", p["brand_fit"]["score"])
    with st.expander("Considered and rejected topics"):
        for r in wf.rejected:
            st.write(f"- **{r['topic']}**: {r['reason']}")
    choice = st.radio("Choose one proposal", [p["id"] for p in wf.proposals],
                      format_func=lambda i: next(p["title"] for p in wf.proposals if p["id"] == i))
    notes = st.text_area("Steering notes (optional)", placeholder="e.g. weeknight-friendly, less dairy")
    c1, c2 = st.columns(2)
    if c1.button("Generate two recipes", type="primary"):
        act(wf.select, choice, notes)
    reject_note = c2.text_input("None fit? Optional note", key="reject_note")
    if c2.button("None of these fit: propose other topics"):
        act(wf.reject_all, reject_note)

if wf.stage in ("review", "approved"):
    st.info(f"Selected: **{wf.selected['title']}** · steering notes: {wf.notes or 'none'}")
    st.subheader("Recipes")
    for r in wf.bundle["recipes"]:
        with st.expander(f"{r['title']} · AI-generated draft"):
            st.write(r["subtitle"])
            st.table(r["ingredients"])
            for n, s in enumerate(r["steps"], 1):
                st.write(f"{n}. {s}")

    st.subheader("Review")
    for rnd in wf.rounds:
        n_open = sum(1 for i in rnd["issues"] if i["status"] == "open")
        with st.expander(f"Round {rnd['round']}: {n_open} open issue(s), {len(rnd['fixed'])} fixed since last round"):
            for i in rnd["issues"]:
                st.write(f"**{i['kind'].upper()}** · {i['criterion']} · {i['message']}")
            for i in rnd["fixed"]:
                st.write(f"🟢 fixed: {i['message']}")

    if wf.stage == "review":
        for notice in wf.notices:
            st.warning(notice)
        open_issues = [i for i in wf.issues if i["status"] == "open"]
        st.markdown("**Open issues**" if open_issues else "**No open issues.**")
        for n, i in enumerate(open_issues):
            with st.container(border=True):
                if i["kind"] == "hard":
                    st.write(f"🛑 HARD (blocks approval, cannot be dismissed) · {i['criterion']}")
                    st.write(i["message"])
                else:
                    st.write(f"⚠️ soft (does not block) · {i['criterion']}")
                    st.write(i["message"])
                    reason = st.text_input("Note for the record (optional: acknowledge this warning)", key=f"reason{n}")
                    if st.button("Acknowledge warning", key=f"ack{n}"):
                        act(wf.acknowledge, i["key"], reason)
        for i in (x for x in wf.issues if x["status"] == "dismissed"):
            st.caption(f"⚪ acknowledged: {i['message']} — {i['dismiss_reason']}")

        st.subheader("Your decision")
        comment = st.text_area("Comment for the recipe agent (needed to send back)")
        ok, why = wf.can_approve()
        c1, c2 = st.columns(2)
        if c1.button("Approve both recipes", type="primary", disabled=not ok, help=why or None):
            act(wf.approve)
        if c2.button(f"Send back ({wf.editor_rounds_left()} left)", disabled=wf.editor_rounds_left() <= 0):
            act(wf.send_back, comment)
        if not ok:
            c1.caption(why)
        with st.expander("Not happy with these recipes at all?"):
            why_discard = st.text_input("Reason (optional)", key="discard_reason")
            if st.button("Discard these recipes and choose another proposal"):
                act(wf.discard, why_discard)
    else:
        st.success("Approved. The two recipe cards were exported:")
        for path in wf.result["cards"]:
            st.code(path)
        warnings = wf.result["approved_with_warnings"]
        if warnings:
            st.warning("Approved with open or dismissed issues:\n\n" +
                       "\n".join(f"- [{w['status']}] {w['message']} {w['dismiss_reason']}" for w in warnings))
        for item in wf.result["nutrition"]:
            n = item["nutrition"]
            st.write(f"**{item['recipe_title']}**: " + ("nutrition pending (Person C)" if n["status"] == "pending"
                                                       else str(n["per_serving"])))
