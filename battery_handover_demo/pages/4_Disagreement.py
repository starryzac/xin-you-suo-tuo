"""Accountable disagreement form."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.models import (  # noqa: E402
    DisagreementReasonType,
    EvidenceStatus,
    UserRole,
)
from battery_handover_demo.schemas import DisagreementCreate  # noqa: E402
from battery_handover_demo.services import raise_disagreement  # noqa: E402
from battery_handover_demo.ui_helpers import (  # noqa: E402
    current_assessment,
    handle_service_result,
    prepare_page,
    render_actor_selector,
    render_missing_evidence,
    render_status_metrics,
    select_handover,
)


prepare_page("Disagreement")
st.title("Disagreement")
st.caption("Every disagreement must identify both a reason and a responsible organization.")

with SessionLocal() as session:
    actor = render_actor_selector(session)
    handover = select_handover(session, actor, key="disagreement_handover")
    if handover is None:
        st.stop()
    assessment = current_assessment(session, handover.id)

    render_status_metrics(handover)
    render_missing_evidence(assessment)

    if assessment is None:
        st.error("A current assessment is required before a disagreement can be raised.")
        st.stop()

    can_raise = (
        actor.role is UserRole.RECEIVER
        and handover.evidence_status is EvidenceStatus.PENDING
    )
    responsible_options = sorted({handover.sender_org, handover.receiver_org})
    with st.form("disagreement_form"):
        reason_type = st.selectbox(
            "Reason type",
            options=list(DisagreementReasonType),
            format_func=lambda item: item.value.replace("_", " ").title(),
        )
        description = st.text_area("Description")
        responsible_org = st.selectbox(
            "Responsible organization",
            options=responsible_options,
            index=0,
        )
        submitted = st.form_submit_button(
            "Create Disagreement",
            disabled=not can_raise,
        )

    if submitted:
        try:
            command = DisagreementCreate(
                handover_id=handover.id,
                assessment_id=assessment.id,
                reason_type=reason_type,
                description=description,
                responsible_org=responsible_org,
            )
            handle_service_result(raise_disagreement(session, actor, command))
        except ValueError as exc:
            st.error(str(exc))

    if actor.role is not UserRole.RECEIVER:
        st.info("Select the Receiver role to submit this form.")
    elif handover.evidence_status is not EvidenceStatus.PENDING:
        st.info(
            "A disagreement can be raised only while the receiver decision is PENDING."
        )
