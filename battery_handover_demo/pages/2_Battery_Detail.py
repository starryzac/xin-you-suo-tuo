"""Identity, handover, evidence, and receiver-decision detail."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.ui_helpers import (  # noqa: E402
    current_assessment,
    display_value,
    prepare_page,
    render_actor_selector,
    render_missing_evidence,
    render_status_metrics,
    select_handover,
)


prepare_page("Battery Detail")
st.title("Battery Detail")

with SessionLocal() as session:
    actor = render_actor_selector(session)
    handover = select_handover(session, actor, key="detail_handover")
    if handover is None:
        st.stop()
    assessment = current_assessment(session, handover.id)

    render_status_metrics(handover)

    identity, transfer = st.columns(2)
    with identity:
        st.subheader("A. Identity")
        st.markdown(
            f"""
- **Battery ID:** `{handover.battery.battery_id}`
- **Manufacturer:** {handover.battery.manufacturer}
- **Model:** {handover.battery.model}
- **Current holder:** {handover.battery.current_holder}
"""
        )
    with transfer:
        st.subheader("B. Handover")
        st.markdown(
            f"""
- **Sender:** {handover.sender_org}
- **Receiver:** {handover.receiver_org}
- **Transfer date:** {display_value(handover.transfer_date)}
- **Physical status:** `{handover.physical_status.value}`
"""
        )

    st.divider()
    evidence, decision = st.columns([2, 1])
    with evidence:
        st.subheader("C. Evidence")
        if assessment is None:
            st.info("No assessment has been submitted.")
        else:
            st.markdown(
                f"""
- **Condition:** {display_value(assessment.condition_statement)}
- **Assessment date:** {display_value(assessment.assessment_date)}
- **Method:** {display_value(assessment.assessment_method)}
- **Provider:** {display_value(assessment.provider_org)}
- **Reference:** {display_value(assessment.evidence_reference)}
- **Version:** {assessment.version}
- **Completeness:** `{handover.completeness_status.value}`
"""
            )
        render_missing_evidence(assessment)
    with decision:
        st.subheader("D. Receiver decision")
        st.metric("Current decision", handover.evidence_status.value)
        st.caption(
            "The receiver decision remains separate from the physical receipt status shown above."
        )

    actions = st.columns(2)
    if actions[0].button("Open Handover Action", width="stretch"):
        st.switch_page("pages/3_Handover_Action.py")
    if actions[1].button("Open Correction / Audit", width="stretch"):
        st.switch_page("pages/5_Audit_Trail.py")
