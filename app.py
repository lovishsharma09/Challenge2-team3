from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from src.challenge2.orchestrator import ChallengeOrchestrator


st.set_page_config(page_title="das schmeckt! Recipe Studio", layout="wide")
st.title("das schmeckt! · Rezept-Workspace")

if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = ChallengeOrchestrator()
if "proposal_payload" not in st.session_state:
    st.session_state.proposal_payload = st.session_state.orchestrator.generate_proposals()

payload = st.session_state.proposal_payload
st.subheader("1. Vorschläge auswählen")

for proposal in payload["proposals"]:
    with st.container(border=True):
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"### #{proposal['rank']} · {proposal['title']}")
            st.write(proposal["trend"]["why_relevant"])
            st.caption(proposal["brand_fit"]["reasoning"])
        with right:
            st.metric("Trend", proposal["trend"]["score"])
            st.metric("Marken-Fit", proposal["brand_fit"]["score"])
            st.metric("Gesamt", proposal["rank_score"])
        st.markdown(
            "**Archiv:** "
            + ", ".join(recipe["title"] for recipe in proposal["archive"]["similar_recipes"])
        )
        st.markdown(
            f"**Risiko:** {proposal['archive']['repetition_risk']}  \n"
            f"**Gap:** {proposal['archive']['content_gap']}"
        )

with st.expander("Abgelehnte Themen"):
    for rejected in payload["rejected_topics"]:
        st.write(f"- **{rejected['topic']}**: {rejected['reason']}")

proposal_ids = [proposal["id"] for proposal in payload["proposals"]]
selected_id = st.selectbox("Proposal", proposal_ids)
selected = next(
    proposal for proposal in payload["proposals"] if proposal["id"] == selected_id
)
steering_notes = st.text_area(
    "Steering notes",
    placeholder="z. B. weniger Milchprodukte, alltagstauglich, maximal 30 Minuten",
)

if st.button("Rezepte generieren", type="primary"):
    st.session_state.result = st.session_state.orchestrator.generate_recipes(
        selected,
        steering_notes,
    )

if "result" in st.session_state:
    result = st.session_state.result
    st.subheader("2. Review-Loops")
    review = result["review"]
    st.write(
        "Status:",
        "BESTANDEN" if review["passed"] else "NICHT BESTANDEN",
        f"({review['loops_used']} Loops)",
    )
    if review["issues"]:
        st.error("\n".join(issue["message"] for issue in review["issues"]))
    for correction in review["corrections_made"]:
        st.info(correction)

    st.subheader("3. Rezepte und Nährwerte")
    for index, recipe in enumerate(result["recipes"]["recipes"]):
        with st.expander(recipe["title"], expanded=index == 0):
            st.write(recipe["subtitle"])
            st.write("**Zutaten**")
            st.table(recipe["ingredients"])
            st.write("**Zubereitung**")
            for step_index, step in enumerate(recipe["steps"], start=1):
                st.write(f"{step_index}. {step}")
            nutrition = result["nutrition"][index]["nutrition"]
            st.write("**Nährwerte pro Portion**")
            st.json(nutrition)

    if result.get("output_html"):
        st.success(f"HTML-Ausgabe: {result['output_html']}")
