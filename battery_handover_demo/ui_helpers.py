"""Shared, presentation-only helpers for the Streamlit pages."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import streamlit as st
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload


PACKAGE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = PACKAGE_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal, create_schema  # noqa: E402
from battery_handover_demo.models import (  # noqa: E402
    Assessment,
    AuditEvent,
    Correction,
    Disagreement,
    Handover,
    User,
    UserRole,
)
from battery_handover_demo.permissions import has_handover_scope  # noqa: E402
from battery_handover_demo.rules import missing_evidence_fields  # noqa: E402
from battery_handover_demo.seed import seed_demo, seed_ui_examples  # noqa: E402



_ROLE_ORDER = {
    UserRole.SENDER: 0,
    UserRole.RECEIVER: 1,
    UserRole.REVIEWER: 2,
    UserRole.REGULATOR: 3,
}


def enum_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if value is None:
        return "—"
    return str(value)


def display_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value.isoformat()
    return enum_value(value)


def configure_page(title: str) -> None:
    st.set_page_config(
        page_title=f"{title} | Battery Handover Prototype",
        page_icon="🔋",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { --ink: #17212b; --muted: #5c6773; --line: #d9e0e6; --accent: #245b78; }
        .stApp { color: var(--ink); }
        [data-testid="stSidebar"] { background: #f6f8fa; border-right: 1px solid var(--line); }
        [data-testid="stMetric"] { border: 1px solid var(--line); padding: 0.75rem 1rem; background: #fbfcfd; }
        h1, h2, h3 { letter-spacing: -0.015em; }
        h1 { color: #18384a; }
        .block-container { padding-top: 2.1rem; padding-bottom: 3rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_demo_database() -> None:
    """Create the local schema and idempotent display examples."""

    create_schema()
    with SessionLocal() as session:
        seed_demo(session)
        seed_ui_examples(session)


def render_sidebar_navigation() -> None:
    st.sidebar.markdown("### Prototype")
    st.sidebar.page_link("app.py", label="Overview", icon="🏠")
    st.sidebar.page_link("pages/1_Battery_List.py", label="Battery List", icon="📋")
    st.sidebar.page_link("pages/2_Battery_Detail.py", label="Battery Detail", icon="🔎")
    st.sidebar.page_link("pages/3_Handover_Action.py", label="Handover Action", icon="🔁")
    st.sidebar.page_link("pages/4_Disagreement.py", label="Disagreement", icon="⚠️")
    st.sidebar.page_link("pages/5_Audit_Trail.py", label="Correction / Audit", icon="🕰️")
    st.sidebar.divider()


def prepare_page(title: str) -> None:
    st.session_state["_prototype_page_key"] = "".join(
        character.lower() if character.isalnum() else "_" for character in title
    )
    configure_page(title)
    render_sidebar_navigation()
    try:
        initialize_demo_database()
    except Exception as exc:
        st.error(f"The local demo database could not be initialized: {exc}")
        st.stop()
    render_flash()


def render_actor_selector(session: Session) -> User:
    users = list(session.scalars(select(User)).all())
    users.sort(key=lambda user: (_ROLE_ORDER[user.role], user.username))
    if not users:
        st.error("No demo identities are available.")
        st.stop()

    user_ids = [user.id for user in users]
    user_by_id = {user.id: user for user in users}
    persistent_key = "active_user_id"
    if st.session_state.get(persistent_key) not in user_ids:
        st.session_state[persistent_key] = user_ids[0]

    page_key = st.session_state.get("_prototype_page_key", "default")
    selector_key = f"_active_user_selector_{page_key}"
    if st.session_state.get(selector_key) not in user_ids:
        st.session_state[selector_key] = st.session_state[persistent_key]

    def persist_selection() -> None:
        st.session_state[persistent_key] = st.session_state[selector_key]

    selected_id = st.sidebar.selectbox(
        "Simulated role",
        options=user_ids,
        key=selector_key,
        on_change=persist_selection,
        format_func=lambda user_id: (
            f"{user_by_id[user_id].role.value.title()} · "
            f"{user_by_id[user_id].username} · {user_by_id[user_id].organization}"
        ),
    )
    st.session_state[persistent_key] = selected_id
    actor = user_by_id[selected_id]
    st.sidebar.caption(
        "Role selection simulates authorization for this proof of concept; it is not real authentication."
    )
    return actor


def accessible_handovers(session: Session, actor: User) -> list[Handover]:
    handovers = list(
        session.scalars(
            select(Handover)
            .options(
                joinedload(Handover.battery),
                selectinload(Handover.assessments),
                selectinload(Handover.disagreements),
            )
            .order_by(Handover.id.desc())
        ).all()
    )
    return [
        handover
        for handover in handovers
        if has_handover_scope(
            actor.role,
            actor.organization,
            sender_org=handover.sender_org,
            receiver_org=handover.receiver_org,
        )
    ]


def select_handover(
    session: Session,
    actor: User,
    *,
    key: str,
    label: str = "Handover record",
) -> Handover | None:
    handovers = accessible_handovers(session, actor)
    if not handovers:
        st.info("No handover record is available to this role.")
        return None

    by_id = {handover.id: handover for handover in handovers}
    ids = list(by_id)
    preferred = st.session_state.get("selected_handover_id")
    if preferred not in by_id:
        preferred = ids[0]
    if st.session_state.get(key) not in by_id:
        st.session_state[key] = preferred

    selected_id = st.selectbox(
        label,
        options=ids,
        key=key,
        format_func=lambda handover_id: (
            f"{by_id[handover_id].battery.battery_id} · "
            f"{by_id[handover_id].physical_status.value} / "
            f"{by_id[handover_id].evidence_status.value} / "
            f"{by_id[handover_id].completeness_status.value}"
        ),
    )
    st.session_state["selected_handover_id"] = selected_id
    return by_id[selected_id]


def current_assessment(session: Session, handover_id: int) -> Assessment | None:
    return session.scalar(
        select(Assessment)
        .where(Assessment.handover_id == handover_id, Assessment.is_current.is_(True))
        .order_by(Assessment.version.desc())
    )


def assessment_versions(session: Session, handover_id: int) -> list[Assessment]:
    return list(
        session.scalars(
            select(Assessment)
            .where(Assessment.handover_id == handover_id)
            .options(joinedload(Assessment.creator))
            .order_by(Assessment.version)
        ).all()
    )


def disagreements_for(session: Session, handover_id: int) -> list[Disagreement]:
    return list(
        session.scalars(
            select(Disagreement)
            .where(Disagreement.handover_id == handover_id)
            .options(joinedload(Disagreement.raiser))
            .order_by(Disagreement.created_at.desc(), Disagreement.id.desc())
        ).all()
    )


def corrections_for(session: Session, handover_id: int) -> list[Correction]:
    return list(
        session.scalars(
            select(Correction)
            .join(Assessment, Correction.assessment_id == Assessment.id)
            .where(Assessment.handover_id == handover_id)
            .options(joinedload(Correction.assessment), joinedload(Correction.corrector))
            .order_by(Correction.corrected_at, Correction.id)
        ).all()
    )


def audit_events_for(session: Session, handover_id: int) -> list[AuditEvent]:
    versions = assessment_versions(session, handover_id)
    disagreements = disagreements_for(session, handover_id)
    conditions = [
        and_(AuditEvent.target_type == "handover", AuditEvent.target_id == handover_id)
    ]
    assessment_ids = [assessment.id for assessment in versions]
    disagreement_ids = [disagreement.id for disagreement in disagreements]
    if assessment_ids:
        conditions.append(
            and_(
                AuditEvent.target_type == "assessment",
                AuditEvent.target_id.in_(assessment_ids),
            )
        )
    if disagreement_ids:
        conditions.append(
            and_(
                AuditEvent.target_type == "disagreement",
                AuditEvent.target_id.in_(disagreement_ids),
            )
        )
    return list(
        session.scalars(
            select(AuditEvent)
            .where(or_(*conditions))
            .options(joinedload(AuditEvent.user))
            .order_by(AuditEvent.timestamp, AuditEvent.id)
        ).all()
    )


def render_status_metrics(handover: Handover) -> None:
    columns = st.columns(3)
    columns[0].metric("Physical status", handover.physical_status.value)
    columns[1].metric("Evidence status", handover.evidence_status.value)
    columns[2].metric("Completeness", handover.completeness_status.value)


def render_missing_evidence(assessment: Assessment | None) -> tuple[str, ...]:
    if assessment is None:
        missing = (
            "assessment_date",
            "assessment_method",
            "provider_org",
            "evidence_reference",
        )
    else:
        missing = missing_evidence_fields(assessment)
    if missing:
        st.warning("Evidence incomplete")
        st.markdown("**Missing:**\n" + "\n".join(f"- `{field}`" for field in missing))
    else:
        st.success("All required provenance fields are present.")
    return missing


def queue_feedback(ok: bool, message: str) -> None:
    st.session_state["_prototype_flash"] = ("success" if ok else "error", message)
    st.rerun()


def handle_service_result(result: Any) -> None:
    queue_feedback(bool(result.ok), str(result.message))


def render_flash() -> None:
    flash = st.session_state.pop("_prototype_flash", None)
    if flash is None:
        return
    level, message = flash
    if level == "success":
        st.success(message)
    else:
        st.error(message)


def rows_to_dataframe(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Normalize enum/date values before passing rows to Streamlit."""

    return [
        {key: display_value(value) for key, value in row.items()}
        for row in rows
    ]
