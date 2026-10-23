"""Idempotent demonstration identities and battery records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Assessment,
    Battery,
    CompletenessStatus,
    EvidenceStatus,
    Handover,
    PhysicalStatus,
    User,
    UserRole,
)


@dataclass(frozen=True, slots=True)
class SeedData:
    users: dict[str, User]
    batteries: dict[str, Battery]


@dataclass(frozen=True, slots=True)
class UiSeedData:
    handovers: dict[str, Handover]
    assessments: dict[str, Assessment]


_USERS = (
    ("sender_a", "Enterprise A", UserRole.SENDER),
    ("receiver_b", "Enterprise B", UserRole.RECEIVER),
    ("reviewer_c", "Reviewer C", UserRole.REVIEWER),
    ("regulator_d", "Authority D", UserRole.REGULATOR),
)

_BATTERIES = (
    ("BAT-001", "Huaxia EV", "HX-72", "Enterprise A", "RETIRED"),
    ("BAT-002", "Huaxia EV", "HX-68", "Enterprise A", "RETIRED"),
    # Kept free of seeded handovers so the Sender can run the workflow from
    # the beginning even after the two display examples are installed.
    ("BAT-003", "Huaxia EV", "HX-75", "Enterprise A", "RETIRED"),
)

_UI_EXAMPLES = {
    "BAT-001": {
        "transfer_date": date(2026, 9, 15),
        "condition_statement": "SOH 72%",
        "assessment_date": None,
        "assessment_method": None,
        "provider_org": "Enterprise A",
        "evidence_reference": "REPORT-001",
        "completeness_status": CompletenessStatus.INCOMPLETE,
        "evidence_status": EvidenceStatus.PENDING,
    },
    "BAT-002": {
        "transfer_date": date(2026, 9, 16),
        "condition_statement": "SOH 69%",
        "assessment_date": date(2026, 9, 16),
        "assessment_method": "Capacity test",
        "provider_org": "Enterprise A",
        "evidence_reference": "REPORT-002",
        "completeness_status": CompletenessStatus.COMPLETE,
        "evidence_status": EvidenceStatus.ACCEPTED,
    },
}


def seed_demo(session: Session) -> SeedData:
    """Create the fixed demo identities once and return their persisted rows.

    Existing rows are retained rather than overwritten.  A conflicting row
    with a reserved seed key is rejected, which keeps repeated startup safe
    without silently changing user-owned demo state.
    """

    try:
        users: dict[str, User] = {}
        for username, organization, role in _USERS:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(username=username, organization=organization, role=role)
                session.add(user)
                session.flush()
            elif user.organization != organization or user.role is not role:
                raise ValueError(f"seed user {username} exists with conflicting identity data")
            users[username] = user

        batteries: dict[str, Battery] = {}
        for battery_id, manufacturer, model, current_holder, lifecycle_status in _BATTERIES:
            battery = session.scalar(
                select(Battery).where(Battery.battery_id == battery_id)
            )
            if battery is None:
                battery = Battery(
                    battery_id=battery_id,
                    manufacturer=manufacturer,
                    model=model,
                    current_holder=current_holder,
                    lifecycle_status=lifecycle_status,
                )
                session.add(battery)
                session.flush()
            batteries[battery_id] = battery

        session.commit()
        return SeedData(users=users, batteries=batteries)
    except Exception:
        session.rollback()
        raise


def seed_ui_examples(session: Session) -> UiSeedData:
    """Idempotently add two ready-to-inspect handover examples.

    ``BAT-001`` demonstrates physical receipt with incomplete, still-pending
    evidence.  ``BAT-002`` demonstrates a complete accepted record.  Existing
    handovers are never reset, so user actions survive application restarts.
    ``BAT-003`` remains untouched for a clean create-handover workflow.
    """

    base = seed_demo(session)
    sender = base.users["sender_a"]
    handovers: dict[str, Handover] = {}
    assessments: dict[str, Assessment] = {}

    try:
        for battery_id, values in _UI_EXAMPLES.items():
            battery = base.batteries[battery_id]
            handover = session.scalar(
                select(Handover)
                .where(Handover.battery_pk == battery.id)
                .order_by(Handover.id)
            )
            if handover is None:
                handover = Handover(
                    battery_pk=battery.id,
                    sender_org="Enterprise A",
                    receiver_org="Enterprise B",
                    transfer_date=values["transfer_date"],
                    physical_status=PhysicalStatus.RECEIVED,
                    evidence_status=values["evidence_status"],
                    completeness_status=values["completeness_status"],
                    created_by=sender.id,
                )
                session.add(handover)
                session.flush()
                assessment = Assessment(
                    handover_id=handover.id,
                    battery_pk=battery.id,
                    condition_statement=values["condition_statement"],
                    assessment_date=values["assessment_date"],
                    assessment_method=values["assessment_method"],
                    provider_org=values["provider_org"],
                    evidence_reference=values["evidence_reference"],
                    version=1,
                    created_by=sender.id,
                    is_current=True,
                )
                session.add(assessment)
                battery.current_holder = "Enterprise B"
                session.flush()
            else:
                assessment = session.scalar(
                    select(Assessment)
                    .where(
                        Assessment.handover_id == handover.id,
                        Assessment.is_current.is_(True),
                    )
                    .order_by(Assessment.version.desc())
                )
                if assessment is None:
                    raise ValueError(
                        f"existing UI example handover for {battery_id} has no current assessment"
                    )
            handovers[battery_id] = handover
            assessments[battery_id] = assessment

        session.commit()
        return UiSeedData(handovers=handovers, assessments=assessments)
    except Exception:
        session.rollback()
        raise
