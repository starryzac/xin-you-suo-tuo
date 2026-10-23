"""Sender setup and three independent receiver actions."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st
from sqlalchemy import select


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.models import (  # noqa: E402
    Battery,
    EvidenceStatus,
    Handover,
    PhysicalStatus,
    User,
    UserRole,
)
from battery_handover_demo.rules import acceptance_decision  # noqa: E402
from battery_handover_demo.schemas import AssessmentCreate, HandoverCreate  # noqa: E402
from battery_handover_demo.services import (  # noqa: E402
    accept_evidence,
    confirm_receipt,
    create_assessment,
    create_handover,
    mark_sent,
)
from battery_handover_demo.ui_helpers import (  # noqa: E402
    current_assessment,
    disagreements_for,
    handle_service_result,
    prepare_page,
    render_actor_selector,
    render_missing_evidence,
    render_status_metrics,
    select_handover,
)


prepare_page("Handover Action")
st.title("Handover Action")
st.caption("Physical receipt and the receiver's evidence decision are recorded independently.")

with SessionLocal() as session:
    actor = render_actor_selector(session)

    if actor.role is UserRole.SENDER:
        with st.expander("Sender workflow", expanded=False):
            st.markdown("#### Create a handover")
            available_batteries = list(
                session.scalars(
                    select(Battery)
                    .where(
                        Battery.current_holder == actor.organization,
                        ~select(Handover.id)
                        .where(
                            Handover.battery_pk == Battery.id,
                            Handover.physical_status.in_(
                                [PhysicalStatus.CREATED, PhysicalStatus.SENT]
                            ),
                        )
                        .exists(),
                    )
                    .order_by(Battery.battery_id)
                ).all()
            )
            receiver_organizations = sorted(
                set(
                    session.scalars(
                        select(User.organization).where(
                            User.role == UserRole.RECEIVER
                        )
                    ).all()
                )
            )
            if available_batteries:
                with st.form("create_handover_form"):
                    battery_pk = st.selectbox(
                        "Battery",
                        options=[battery.id for battery in available_batteries],
                        format_func=lambda item_id: next(
                            battery.battery_id
                            for battery in available_batteries
                            if battery.id == item_id
                        ),
                    )
                    receiver_org = st.selectbox(
                        "Receiver organization",
                        options=receiver_organizations,
                    )
                    transfer_date = st.date_input("Transfer date", value=date.today())
                    create_submitted = st.form_submit_button("Create Handover")
                if create_submitted:
                    try:
                        command = HandoverCreate(
                            battery_pk=battery_pk,
                            sender_org=actor.organization,
                            receiver_org=receiver_org,
                            transfer_date=transfer_date,
                        )
                        result = create_handover(session, actor, command)
                        if result.ok and result.value is not None:
                            st.session_state["selected_handover_id"] = result.value.id
                            st.session_state["action_handover"] = result.value.id
                        handle_service_result(result)
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.info("No battery currently held by this sender is available.")

    handover = select_handover(session, actor, key="action_handover")
    if handover is None:
        st.stop()
    assessment = current_assessment(session, handover.id)
    disagreements = disagreements_for(session, handover.id)

    render_status_metrics(handover)
    render_missing_evidence(assessment)

    if actor.role is UserRole.SENDER:
        with st.expander("Submit or dispatch sender evidence", expanded=assessment is None):
            if assessment is None:
                with st.form("assessment_form"):
                    condition = st.text_input("Condition statement", "SOH 72%")
                    assessment_date_text = st.text_input(
                        "Assessment date (YYYY-MM-DD, optional)"
                    )
                    method = st.text_input("Assessment method (optional)")
                    provider = st.text_input("Provider organization (optional)")
                    reference = st.text_input("Evidence reference (optional)")
                    assessment_submitted = st.form_submit_button("Submit Assessment")
                if assessment_submitted:
                    try:
                        parsed_date = (
                            date.fromisoformat(assessment_date_text.strip())
                            if assessment_date_text.strip()
                            else None
                        )
                        command = AssessmentCreate(
                            handover_id=handover.id,
                            battery_pk=handover.battery_pk,
                            condition_statement=condition,
                            assessment_date=parsed_date,
                            assessment_method=method,
                            provider_org=provider,
                            evidence_reference=reference,
                        )
                        handle_service_result(create_assessment(session, actor, command))
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.info(f"Current evidence version: {assessment.version}")

            if st.button(
                "Mark Physical Transfer as Sent",
                disabled=handover.physical_status is not PhysicalStatus.CREATED,
            ):
                handle_service_result(mark_sent(session, actor, handover.id))

    st.subheader("Independent receiver actions")
    decision = acceptance_decision(handover, assessment, disagreements)
    if decision.allowed:
        st.success("The current evidence is eligible for receiver acceptance.")
    else:
        st.caption(f"Acceptance eligibility: {decision.reason}")

    is_receiver = actor.role is UserRole.RECEIVER
    action_columns = st.columns(3)
    if action_columns[0].button(
        "Confirm Physical Receipt",
        width="stretch",
        disabled=(
            not is_receiver or handover.physical_status is not PhysicalStatus.SENT
        ),
    ):
        handle_service_result(confirm_receipt(session, actor, handover.id))
    if action_columns[1].button(
        "Accept Evidence",
        width="stretch",
        disabled=not is_receiver or not decision.allowed,
    ):
        handle_service_result(accept_evidence(session, actor, handover.id))
    if action_columns[2].button(
        "Raise Disagreement",
        width="stretch",
        disabled=(
            not is_receiver
            or assessment is None
            or handover.evidence_status is not EvidenceStatus.PENDING
        ),
    ):
        st.session_state["selected_handover_id"] = handover.id
        st.switch_page("pages/4_Disagreement.py")

    if not is_receiver:
        st.info("Select the Receiver role to use the three receiver actions.")
