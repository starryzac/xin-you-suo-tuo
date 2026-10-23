"""Evidence versions, corrections, review outcomes, and regulator audit."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.models import (  # noqa: E402
    DisagreementStatus,
    EvidenceStatus,
    UserRole,
)
from battery_handover_demo.schemas import CorrectionCreate  # noqa: E402
from battery_handover_demo.services import (  # noqa: E402
    apply_correction,
    start_review,
    submit_review_outcome,
)
from battery_handover_demo.ui_helpers import (  # noqa: E402
    assessment_versions,
    audit_events_for,
    corrections_for,
    current_assessment,
    disagreements_for,
    display_value,
    handle_service_result,
    prepare_page,
    render_actor_selector,
    render_status_metrics,
    rows_to_dataframe,
    select_handover,
)


CORRECTABLE_FIELDS = (
    "condition_statement",
    "assessment_date",
    "assessment_method",
    "provider_org",
    "evidence_reference",
)


prepare_page("Correction / Audit Trail")
st.title("Correction / Audit Trail")
st.caption("Corrections create a new evidence version; the earlier version remains visible.")

with SessionLocal() as session:
    actor = render_actor_selector(session)
    handover = select_handover(session, actor, key="audit_handover")
    if handover is None:
        st.stop()

    render_status_metrics(handover)

    versions = assessment_versions(session, handover.id)
    st.subheader("Evidence versions")
    version_rows = rows_to_dataframe(
        {
            "Version": item.version,
            "Current": item.is_current,
            "Condition": item.condition_statement,
            "Assessment date": item.assessment_date,
            "Method": item.assessment_method,
            "Provider": item.provider_org,
            "Reference": item.evidence_reference,
            "Created by": item.creator.username,
            "Created at": item.created_at,
        }
        for item in versions
    )
    if version_rows:
        st.dataframe(version_rows, hide_index=True, width="stretch")
    else:
        st.info("No evidence version has been submitted.")

    corrections = corrections_for(session, handover.id)
    st.subheader("Correction history")
    correction_rows = rows_to_dataframe(
        {
            "Source version": item.assessment.version,
            "Field": item.field_name,
            "Old value": item.old_value,
            "New value": item.new_value,
            "Reason": item.reason,
            "Actor": item.corrector.username,
            "Timestamp": item.corrected_at,
        }
        for item in corrections
    )
    if correction_rows:
        st.dataframe(correction_rows, hide_index=True, width="stretch")
    else:
        st.info("No correction has been recorded.")

    disagreements = disagreements_for(session, handover.id)
    st.subheader("Disagreements and review")
    disagreement_rows = rows_to_dataframe(
        {
            "ID": item.id,
            "Reason": item.reason_type,
            "Description": item.description,
            "Responsible organization": item.responsible_org,
            "Status": item.status,
            "Raised by": item.raiser.username,
            "Created at": item.created_at,
            "Resolved at": item.resolved_at,
        }
        for item in disagreements
    )
    if disagreement_rows:
        st.dataframe(disagreement_rows, hide_index=True, width="stretch")
    else:
        st.info("No disagreement has been recorded.")

    if actor.role is UserRole.REVIEWER:
        selected_disagreement = None
        if disagreements:
            by_id = {item.id: item for item in disagreements}
            selected_disagreement_id = st.selectbox(
                "Disagreement under review",
                options=list(by_id),
                format_func=lambda item_id: (
                    f"#{item_id} · {by_id[item_id].reason_type.value} · "
                    f"{by_id[item_id].status.value}"
                ),
            )
            selected_disagreement = by_id[selected_disagreement_id]

            if st.button(
                "Start Review",
                disabled=selected_disagreement.status is not DisagreementStatus.OPEN,
            ):
                handle_service_result(
                    start_review(session, actor, selected_disagreement.id)
                )
        else:
            st.info(
                "No disagreement is recorded. An authorized correction can still "
                "version pending or previously accepted evidence."
            )

        current = current_assessment(session, handover.id)
        correction_blocked = (
            current is None or handover.evidence_status is EvidenceStatus.DISPUTED
        )
        st.markdown("#### Authorized correction")
        field_name = st.selectbox(
            "Field",
            options=CORRECTABLE_FIELDS,
            key=f"correction_field_{handover.id}",
        )
        current_value = getattr(current, field_name, None) if current is not None else None
        with st.form("correction_form"):
            st.caption(f"Current value: {display_value(current_value)}")
            new_value = st.text_input(
                "New value",
                help="Use YYYY-MM-DD for assessment_date. Leave blank only to record a null value.",
            )
            correction_reason = st.text_area("Correction reason")
            correction_submitted = st.form_submit_button(
                "Create New Evidence Version",
                disabled=correction_blocked,
            )
        if handover.evidence_status is EvidenceStatus.DISPUTED:
            st.caption("Start review before correcting disputed evidence.")
        if correction_submitted and current is not None:
            try:
                command = CorrectionCreate(
                    assessment_id=current.id,
                    field_name=field_name,
                    new_value=new_value,
                    reason=correction_reason,
                )
                handle_service_result(apply_correction(session, actor, command))
            except ValueError as exc:
                st.error(str(exc))

        if selected_disagreement is not None:
            with st.form("review_outcome_form"):
                st.markdown("#### Review outcome")
                outcome = st.selectbox(
                    "Outcome",
                    options=[DisagreementStatus.RESOLVED, DisagreementStatus.UNRESOLVED],
                    format_func=lambda item: item.value,
                )
                outcome_reason = st.text_area("Outcome note (optional)")
                outcome_submitted = st.form_submit_button(
                    "Submit Review Outcome",
                    disabled=(
                        selected_disagreement.status
                        is not DisagreementStatus.UNDER_REVIEW
                    ),
                )
            if outcome_submitted:
                handle_service_result(
                    submit_review_outcome(
                        session,
                        actor,
                        selected_disagreement.id,
                        outcome,
                        outcome_reason or None,
                    )
                )
    else:
        st.caption("Reviewer controls are available only to the Reviewer role.")

    st.subheader("Audit events")
    if actor.role is UserRole.REGULATOR:
        events = audit_events_for(session, handover.id)
        event_rows = rows_to_dataframe(
            {
                "Timestamp": item.timestamp,
                "Action": item.action,
                "Actor": item.user.username,
                "Target": f"{item.target_type}:{item.target_id}",
                "Success": item.success,
                "Old value": item.old_value,
                "New value": item.new_value,
                "Reason": item.reason,
            }
            for item in events
        )
        if event_rows:
            st.dataframe(event_rows, hide_index=True, width="stretch")
        else:
            st.info("No audit event has been recorded for this handover.")
    else:
        st.info("Select the Regulator role to inspect the full read-only audit trail.")
