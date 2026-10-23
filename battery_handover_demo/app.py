"""Streamlit entry point for the battery handover prototype."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.models import CompletenessStatus, EvidenceStatus  # noqa: E402
from battery_handover_demo.ui_helpers import (  # noqa: E402
    accessible_handovers,
    prepare_page,
    render_actor_selector,
)


prepare_page("Overview")

st.title("Battery Handover Accountability Prototype")
st.caption(
    "A functional proof of concept for separating physical transfer from acceptance of the accompanying evidence."
)

with SessionLocal() as session:
    actor = render_actor_selector(session)
    handovers = accessible_handovers(session, actor)

    incomplete = sum(
        handover.completeness_status is CompletenessStatus.INCOMPLETE
        for handover in handovers
    )
    open_decisions = sum(
        handover.evidence_status is not EvidenceStatus.ACCEPTED
        for handover in handovers
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Visible handovers", len(handovers))
    col2.metric("Incomplete evidence", incomplete)
    col3.metric("Decisions not accepted", open_decisions)

st.subheader("Accountability workflow")
st.markdown(
    """
1. Identify the battery and the organizations in the transfer.
2. Preserve the source, method, date, and reference for condition evidence.
3. Record physical receipt independently from the receiver's evidence decision.
4. Assign disagreements to a responsible organization.
5. Correct evidence through a new version and retain the earlier record.
6. Preserve successful and denied actions in an auditable history.
"""
)

st.subheader("Open a working view")
links = st.columns(3)
with links[0]:
    st.page_link("pages/1_Battery_List.py", label="Battery List", icon="📋", width="stretch")
    st.page_link("pages/2_Battery_Detail.py", label="Battery Detail", icon="🔎", width="stretch")
with links[1]:
    st.page_link("pages/3_Handover_Action.py", label="Handover Action", icon="🔁", width="stretch")
    st.page_link("pages/4_Disagreement.py", label="Disagreement", icon="⚠️", width="stretch")
with links[2]:
    st.page_link("pages/5_Audit_Trail.py", label="Correction / Audit", icon="🕰️", width="stretch")

st.info(
    "This prototype does not assess battery safety, determine legal compliance, connect to a national traceability platform, or demonstrate industrial performance."
)
