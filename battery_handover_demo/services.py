"""Transactional application services for the handover workflow.

Every public mutation follows one rule: successful business changes and their
audit event commit together; failed changes are rolled back before a separate
``success=False`` audit event is saved.  Callers therefore receive a simple
result object and never need to coordinate partial database changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Assessment,
    AuditEvent,
    Battery,
    CompletenessStatus,
    Correction,
    Disagreement,
    DisagreementStatus,
    EvidenceStatus,
    Handover,
    PhysicalStatus,
    User,
    UserRole,
    utc_now,
)
from .permissions import (
    PermissionAction,
    PermissionDenied,
    require_handover_scope,
    require_permission,
)
from .rules import (
    DomainRuleViolation,
    acceptance_decision,
    derive_completeness,
    require_evidence_transition,
    require_physical_transition,
    valid_disagreement,
)
from .schemas import AssessmentCreate, CorrectionCreate, DisagreementCreate, HandoverCreate


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ServiceResult(Generic[T]):
    """Stable return type used by the UI, scenarios, and tests."""

    ok: bool
    message: str
    value: T | None = None


@dataclass(frozen=True, slots=True)
class _Mutation(Generic[T]):
    value: T
    target_type: str
    target_id: int
    old_value: Any = None
    new_value: Any = None


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _audit_value(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _run_mutation(
    session: Session,
    actor: User,
    *,
    action: str,
    attempted_target_type: str,
    attempted_target_id: int,
    attempted_new_value: Any,
    operation: Callable[[User], _Mutation[T]],
) -> ServiceResult[T]:
    """Run one mutation with all-or-nothing business state and durable audit."""

    actor_id = int(actor.id or 0)
    if actor_id < 1:
        session.rollback()
        return ServiceResult(False, "actor must be a persisted user")

    try:
        persisted_actor = session.get(User, actor_id)
        if persisted_actor is None:
            raise PermissionDenied("actor is not present in this database")

        mutation = operation(persisted_actor)
        if mutation.target_id < 1:
            raise RuntimeError("audit target must be persisted before commit")

        session.add(
            AuditEvent(
                user_id=actor_id,
                action=action,
                target_type=mutation.target_type,
                target_id=mutation.target_id,
                old_value=_audit_value(mutation.old_value),
                new_value=_audit_value(mutation.new_value),
                success=True,
            )
        )
        session.commit()
        return ServiceResult(True, f"{action} succeeded", mutation.value)
    except Exception as exc:  # one boundary keeps every failed path atomic
        reason = _message(exc)
        session.rollback()

        # A denied or invalid action remains evidence.  It is committed only
        # after the failed business transaction has been completely rolled back.
        try:
            if session.get(User, actor_id) is None:
                return ServiceResult(False, reason)
            session.add(
                AuditEvent(
                    user_id=actor_id,
                    action=action,
                    target_type=attempted_target_type,
                    target_id=max(1, int(attempted_target_id)),
                    new_value=_audit_value(attempted_new_value),
                    success=False,
                    reason=reason,
                )
            )
            session.commit()
        except Exception as audit_exc:
            session.rollback()
            return ServiceResult(
                False,
                f"{reason} (failed audit could not be saved: {_message(audit_exc)})",
            )
        return ServiceResult(False, reason)


def _handover_or_fail(session: Session, handover_id: int) -> Handover:
    handover = session.get(Handover, handover_id)
    if handover is None:
        raise DomainRuleViolation(f"handover {handover_id} does not exist")
    return handover


def _disagreement_or_fail(session: Session, disagreement_id: int) -> Disagreement:
    disagreement = session.get(Disagreement, disagreement_id)
    if disagreement is None:
        raise DomainRuleViolation(f"disagreement {disagreement_id} does not exist")
    return disagreement


def _current_assessment(session: Session, handover_id: int) -> Assessment | None:
    return session.scalar(
        select(Assessment)
        .where(Assessment.handover_id == handover_id, Assessment.is_current.is_(True))
        .order_by(Assessment.version.desc())
    )


def _assessment_snapshot(assessment: Assessment) -> dict[str, Any]:
    return {
        "id": assessment.id,
        "handover_id": assessment.handover_id,
        "battery_pk": assessment.battery_pk,
        "condition_statement": assessment.condition_statement,
        "assessment_date": assessment.assessment_date,
        "assessment_method": assessment.assessment_method,
        "provider_org": assessment.provider_org,
        "evidence_reference": assessment.evidence_reference,
        "version": assessment.version,
        "is_current": assessment.is_current,
    }


def _handover_snapshot(handover: Handover) -> dict[str, Any]:
    return {
        "id": handover.id,
        "battery_pk": handover.battery_pk,
        "physical_status": handover.physical_status,
        "evidence_status": handover.evidence_status,
        "completeness_status": handover.completeness_status,
    }


def _require_scope(actor: User, handover: Handover) -> None:
    require_handover_scope(
        actor.role,
        actor.organization,
        sender_org=handover.sender_org,
        receiver_org=handover.receiver_org,
    )


def create_handover(
    session: Session, actor: User, command: HandoverCreate
) -> ServiceResult[Handover]:
    """Create a sender-owned handover in CREATED/PENDING state."""

    def operation(current_actor: User) -> _Mutation[Handover]:
        require_permission(current_actor.role, PermissionAction.CREATE_HANDOVER)
        require_handover_scope(
            current_actor.role,
            current_actor.organization,
            sender_org=command.sender_org,
            receiver_org=command.receiver_org,
        )
        battery = session.get(Battery, command.battery_pk)
        if battery is None:
            raise DomainRuleViolation(f"battery {command.battery_pk} does not exist")
        if battery.current_holder != command.sender_org:
            raise DomainRuleViolation("sender organization is not the battery's current holder")
        receiver_user_id = session.scalar(
            select(User.id)
            .where(
                User.role == UserRole.RECEIVER,
                User.organization == command.receiver_org,
            )
            .limit(1)
        )
        if receiver_user_id is None:
            raise DomainRuleViolation(
                "receiver organization has no configured Receiver identity"
            )
        active_handover_id = session.scalar(
            select(Handover.id)
            .where(
                Handover.battery_pk == battery.id,
                Handover.physical_status.in_(
                    [PhysicalStatus.CREATED, PhysicalStatus.SENT]
                ),
            )
            .limit(1)
        )
        if active_handover_id is not None:
            raise DomainRuleViolation(
                f"battery already has active handover {active_handover_id}"
            )

        handover = Handover(
            battery_pk=command.battery_pk,
            sender_org=command.sender_org,
            receiver_org=command.receiver_org,
            transfer_date=command.transfer_date,
            physical_status=PhysicalStatus.CREATED,
            evidence_status=EvidenceStatus.PENDING,
            completeness_status=CompletenessStatus.INCOMPLETE,
            created_by=current_actor.id,
        )
        session.add(handover)
        session.flush()
        return _Mutation(
            handover,
            "handover",
            handover.id,
            new_value=_handover_snapshot(handover),
        )

    return _run_mutation(
        session,
        actor,
        action="CREATE_HANDOVER",
        attempted_target_type="battery",
        attempted_target_id=command.battery_pk,
        attempted_new_value=command,
        operation=operation,
    )


def create_assessment(
    session: Session, actor: User, command: AssessmentCreate
) -> ServiceResult[Assessment]:
    """Submit the immutable first assessment version for a handover."""

    def operation(current_actor: User) -> _Mutation[Assessment]:
        require_permission(current_actor.role, PermissionAction.SUBMIT_ASSESSMENT)
        handover = _handover_or_fail(session, command.handover_id)
        _require_scope(current_actor, handover)
        if handover.battery_pk != command.battery_pk:
            raise DomainRuleViolation("assessment battery does not match the handover")
        if _current_assessment(session, handover.id) is not None:
            raise DomainRuleViolation(
                "a current assessment already exists; use an authorized correction"
            )

        assessment = Assessment(
            handover_id=handover.id,
            battery_pk=handover.battery_pk,
            condition_statement=command.condition_statement,
            assessment_date=command.assessment_date,
            assessment_method=command.assessment_method,
            provider_org=command.provider_org,
            evidence_reference=command.evidence_reference,
            version=1,
            created_by=current_actor.id,
            is_current=True,
        )
        handover.completeness_status = derive_completeness(assessment)
        handover.evidence_status = EvidenceStatus.PENDING
        session.add(assessment)
        session.flush()
        return _Mutation(
            assessment,
            "assessment",
            assessment.id,
            new_value=_assessment_snapshot(assessment),
        )

    return _run_mutation(
        session,
        actor,
        action="SUBMIT_ASSESSMENT",
        attempted_target_type="handover",
        attempted_target_id=command.handover_id,
        attempted_new_value=command,
        operation=operation,
    )


def mark_sent(session: Session, actor: User, handover_id: int) -> ServiceResult[Handover]:
    """Advance the physical track from CREATED to SENT."""

    def operation(current_actor: User) -> _Mutation[Handover]:
        require_permission(current_actor.role, PermissionAction.CREATE_HANDOVER)
        handover = _handover_or_fail(session, handover_id)
        _require_scope(current_actor, handover)
        if handover.battery.current_holder != handover.sender_org:
            raise DomainRuleViolation("battery is no longer held by the sender")
        old = _handover_snapshot(handover)
        require_physical_transition(handover.physical_status, PhysicalStatus.SENT)
        handover.physical_status = PhysicalStatus.SENT
        session.flush()
        return _Mutation(
            handover,
            "handover",
            handover.id,
            old_value=old,
            new_value=_handover_snapshot(handover),
        )

    return _run_mutation(
        session,
        actor,
        action="MARK_SENT",
        attempted_target_type="handover",
        attempted_target_id=handover_id,
        attempted_new_value={"physical_status": PhysicalStatus.SENT},
        operation=operation,
    )


def confirm_receipt(
    session: Session, actor: User, handover_id: int
) -> ServiceResult[Handover]:
    """Confirm physical receipt without changing evidence acceptance."""

    def operation(current_actor: User) -> _Mutation[Handover]:
        require_permission(current_actor.role, PermissionAction.CONFIRM_PHYSICAL_RECEIPT)
        handover = _handover_or_fail(session, handover_id)
        _require_scope(current_actor, handover)
        old = _handover_snapshot(handover)
        old["current_holder"] = handover.battery.current_holder
        require_physical_transition(handover.physical_status, PhysicalStatus.RECEIVED)
        handover.physical_status = PhysicalStatus.RECEIVED
        handover.battery.current_holder = handover.receiver_org
        session.flush()
        new = _handover_snapshot(handover)
        new["current_holder"] = handover.battery.current_holder
        return _Mutation(
            handover,
            "handover",
            handover.id,
            old_value=old,
            new_value=new,
        )

    return _run_mutation(
        session,
        actor,
        action="CONFIRM_RECEIPT",
        attempted_target_type="handover",
        attempted_target_id=handover_id,
        attempted_new_value={"physical_status": PhysicalStatus.RECEIVED},
        operation=operation,
    )


def accept_evidence(
    session: Session, actor: User, handover_id: int
) -> ServiceResult[Handover]:
    """Accept only complete current evidence with no active disagreement."""

    def operation(current_actor: User) -> _Mutation[Handover]:
        require_permission(current_actor.role, PermissionAction.ACCEPT_EVIDENCE)
        handover = _handover_or_fail(session, handover_id)
        _require_scope(current_actor, handover)
        if handover.physical_status is not PhysicalStatus.RECEIVED:
            raise DomainRuleViolation("physical receipt must be confirmed first")
        assessment = _current_assessment(session, handover.id)
        decision = acceptance_decision(handover, assessment, handover.disagreements)
        if not decision.allowed:
            raise DomainRuleViolation(decision.reason or "evidence cannot be accepted")
        old = _handover_snapshot(handover)
        require_evidence_transition(handover.evidence_status, EvidenceStatus.ACCEPTED)
        handover.evidence_status = EvidenceStatus.ACCEPTED
        session.flush()
        return _Mutation(
            handover,
            "handover",
            handover.id,
            old_value=old,
            new_value=_handover_snapshot(handover),
        )

    return _run_mutation(
        session,
        actor,
        action="ACCEPT_EVIDENCE",
        attempted_target_type="handover",
        attempted_target_id=handover_id,
        attempted_new_value={"evidence_status": EvidenceStatus.ACCEPTED},
        operation=operation,
    )


def raise_disagreement(
    session: Session, actor: User, command: DisagreementCreate
) -> ServiceResult[Disagreement]:
    """Open an accountable disagreement while preserving source evidence."""

    def operation(current_actor: User) -> _Mutation[Disagreement]:
        require_permission(current_actor.role, PermissionAction.RAISE_DISAGREEMENT)
        handover = _handover_or_fail(session, command.handover_id)
        _require_scope(current_actor, handover)
        assessment = session.get(Assessment, command.assessment_id)
        if assessment is None or assessment.handover_id != handover.id:
            raise DomainRuleViolation("assessment does not belong to the handover")
        if not assessment.is_current:
            raise DomainRuleViolation("a disagreement must reference the current assessment")
        if not valid_disagreement(
            reason_type=command.reason_type,
            responsible_org=command.responsible_org,
        ):
            raise DomainRuleViolation("reason type and responsible organization are required")

        old = _handover_snapshot(handover)
        require_evidence_transition(handover.evidence_status, EvidenceStatus.DISPUTED)
        disagreement = Disagreement(
            handover_id=handover.id,
            assessment_id=assessment.id,
            raised_by=current_actor.id,
            reason_type=command.reason_type,
            description=command.description,
            responsible_org=command.responsible_org,
            status=DisagreementStatus.OPEN,
        )
        handover.evidence_status = EvidenceStatus.DISPUTED
        session.add(disagreement)
        session.flush()
        return _Mutation(
            disagreement,
            "disagreement",
            disagreement.id,
            old_value=old,
            new_value={
                "handover": _handover_snapshot(handover),
                "reason_type": disagreement.reason_type,
                "responsible_org": disagreement.responsible_org,
                "status": disagreement.status,
            },
        )

    return _run_mutation(
        session,
        actor,
        action="RAISE_DISAGREEMENT",
        attempted_target_type="handover",
        attempted_target_id=command.handover_id,
        attempted_new_value=command,
        operation=operation,
    )


def start_review(
    session: Session, actor: User, disagreement_id: int
) -> ServiceResult[Disagreement]:
    """Move an open disagreement and its handover into formal review."""

    def operation(current_actor: User) -> _Mutation[Disagreement]:
        require_permission(current_actor.role, PermissionAction.START_REVIEW)
        disagreement = _disagreement_or_fail(session, disagreement_id)
        handover = disagreement.handover
        _require_scope(current_actor, handover)
        if disagreement.status is not DisagreementStatus.OPEN:
            raise DomainRuleViolation("only an OPEN disagreement can enter review")
        old = {
            "disagreement_status": disagreement.status,
            "handover": _handover_snapshot(handover),
        }
        require_evidence_transition(handover.evidence_status, EvidenceStatus.UNDER_REVIEW)
        disagreement.status = DisagreementStatus.UNDER_REVIEW
        handover.evidence_status = EvidenceStatus.UNDER_REVIEW
        session.flush()
        return _Mutation(
            disagreement,
            "disagreement",
            disagreement.id,
            old_value=old,
            new_value={
                "disagreement_status": disagreement.status,
                "handover": _handover_snapshot(handover),
            },
        )

    return _run_mutation(
        session,
        actor,
        action="START_REVIEW",
        attempted_target_type="disagreement",
        attempted_target_id=disagreement_id,
        attempted_new_value={"status": DisagreementStatus.UNDER_REVIEW},
        operation=operation,
    )


_CORRECTABLE_FIELDS = frozenset(
    {
        "condition_statement",
        "assessment_date",
        "assessment_method",
        "provider_org",
        "evidence_reference",
    }
)


def _coerce_correction_value(field_name: str, value: str | None) -> object | None:
    if field_name == "assessment_date":
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise DomainRuleViolation("assessment_date must use YYYY-MM-DD") from exc
    if field_name == "condition_statement":
        if value is None or not value.strip():
            raise DomainRuleViolation("condition_statement cannot be empty")
        return value.strip()
    return value.strip() if isinstance(value, str) and value.strip() else None


def _display_value(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return str(value)


def apply_correction(
    session: Session, actor: User, command: CorrectionCreate
) -> ServiceResult[Assessment]:
    """Create a new assessment version and retain an immutable correction log."""

    def operation(current_actor: User) -> _Mutation[Assessment]:
        require_permission(current_actor.role, PermissionAction.APPLY_CORRECTION)
        source = session.get(Assessment, command.assessment_id)
        if source is None:
            raise DomainRuleViolation(f"assessment {command.assessment_id} does not exist")
        handover = source.handover
        _require_scope(current_actor, handover)
        if not source.is_current:
            raise DomainRuleViolation("only the current assessment can be corrected")
        if command.field_name not in _CORRECTABLE_FIELDS:
            raise DomainRuleViolation(f"{command.field_name} is not a correctable evidence field")
        if handover.evidence_status is EvidenceStatus.DISPUTED:
            raise DomainRuleViolation("start review before correcting disputed evidence")

        old_snapshot = _assessment_snapshot(source)
        old_value = getattr(source, command.field_name)
        new_value = _coerce_correction_value(command.field_name, command.new_value)
        if old_value == new_value:
            raise DomainRuleViolation("correction must change the selected value")

        next_version = int(
            session.scalar(
                select(func.max(Assessment.version)).where(
                    Assessment.handover_id == handover.id
                )
            )
            or 0
        ) + 1
        values = {
            "condition_statement": source.condition_statement,
            "assessment_date": source.assessment_date,
            "assessment_method": source.assessment_method,
            "provider_org": source.provider_org,
            "evidence_reference": source.evidence_reference,
        }
        values[command.field_name] = new_value
        source.is_current = False
        revised = Assessment(
            handover_id=source.handover_id,
            battery_pk=source.battery_pk,
            version=next_version,
            created_by=current_actor.id,
            is_current=True,
            **values,
        )
        correction = Correction(
            assessment_id=source.id,
            field_name=command.field_name,
            old_value=_display_value(old_value),
            new_value=_display_value(new_value),
            reason=command.reason,
            corrected_by=current_actor.id,
        )
        session.add_all([revised, correction])
        session.flush()

        handover.completeness_status = derive_completeness(revised)
        # An accepted or previously unresolved evidence version must return to
        # PENDING after it changes. During an active review, keep the review
        # track open until the reviewer explicitly records RESOLVED or
        # UNRESOLVED; otherwise the latter outcome would become unreachable.
        if handover.evidence_status in {
            EvidenceStatus.ACCEPTED,
            EvidenceStatus.UNRESOLVED,
        }:
            require_evidence_transition(handover.evidence_status, EvidenceStatus.PENDING)
            handover.evidence_status = EvidenceStatus.PENDING
        session.flush()
        return _Mutation(
            revised,
            "assessment",
            revised.id,
            old_value=old_snapshot,
            new_value={
                "assessment": _assessment_snapshot(revised),
                "correction_id": correction.id,
                "reason": correction.reason,
            },
        )

    return _run_mutation(
        session,
        actor,
        action="APPLY_CORRECTION",
        attempted_target_type="assessment",
        attempted_target_id=command.assessment_id,
        attempted_new_value=command,
        operation=operation,
    )


def submit_review_outcome(
    session: Session,
    actor: User,
    disagreement_id: int,
    outcome: DisagreementStatus,
    reason: str | None = None,
) -> ServiceResult[Disagreement]:
    """Close review as RESOLVED or retain a visible UNRESOLVED outcome."""

    def operation(current_actor: User) -> _Mutation[Disagreement]:
        require_permission(current_actor.role, PermissionAction.SUBMIT_REVIEW_OUTCOME)
        disagreement = _disagreement_or_fail(session, disagreement_id)
        handover = disagreement.handover
        _require_scope(current_actor, handover)
        normalized_outcome = DisagreementStatus(outcome)
        if normalized_outcome not in {
            DisagreementStatus.RESOLVED,
            DisagreementStatus.UNRESOLVED,
        }:
            raise DomainRuleViolation("review outcome must be RESOLVED or UNRESOLVED")
        if disagreement.status is not DisagreementStatus.UNDER_REVIEW:
            raise DomainRuleViolation("review outcome requires an UNDER_REVIEW disagreement")

        old = {
            "disagreement_status": disagreement.status,
            "handover": _handover_snapshot(handover),
        }
        if normalized_outcome is DisagreementStatus.RESOLVED:
            if handover.evidence_status is EvidenceStatus.UNDER_REVIEW:
                require_evidence_transition(handover.evidence_status, EvidenceStatus.PENDING)
                handover.evidence_status = EvidenceStatus.PENDING
            elif handover.evidence_status is not EvidenceStatus.PENDING:
                raise DomainRuleViolation("resolved review must return evidence to PENDING")
            disagreement.status = DisagreementStatus.RESOLVED
            disagreement.resolved_at = utc_now()
        else:
            require_evidence_transition(handover.evidence_status, EvidenceStatus.UNRESOLVED)
            handover.evidence_status = EvidenceStatus.UNRESOLVED
            disagreement.status = DisagreementStatus.UNRESOLVED
            disagreement.resolved_at = None
        session.flush()
        return _Mutation(
            disagreement,
            "disagreement",
            disagreement.id,
            old_value=old,
            new_value={
                "disagreement_status": disagreement.status,
                "handover": _handover_snapshot(handover),
                "review_reason": reason,
            },
        )

    try:
        normalized = DisagreementStatus(outcome)
    except (TypeError, ValueError):
        normalized = str(outcome)
    return _run_mutation(
        session,
        actor,
        action="SUBMIT_REVIEW_OUTCOME",
        attempted_target_type="disagreement",
        attempted_target_id=disagreement_id,
        attempted_new_value={"status": normalized, "reason": reason},
        operation=operation,
    )
