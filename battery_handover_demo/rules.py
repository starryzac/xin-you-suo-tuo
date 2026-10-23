"""Pure governance rules shared by services, UI, and automated scenarios."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .models import (
    CompletenessStatus,
    DisagreementStatus,
    EvidenceStatus,
    PhysicalStatus,
)


class AssessmentLike(Protocol):
    assessment_date: object | None
    assessment_method: str | None
    provider_org: str | None
    evidence_reference: str | None
    is_current: bool


class HandoverLike(Protocol):
    evidence_status: EvidenceStatus | str


class DisagreementLike(Protocol):
    status: DisagreementStatus | str


REQUIRED_PROVENANCE_FIELDS = (
    "assessment_date",
    "assessment_method",
    "provider_org",
    "evidence_reference",
)

ACTIVE_DISAGREEMENT_STATUSES = frozenset(
    {
        DisagreementStatus.OPEN,
        DisagreementStatus.UNDER_REVIEW,
        DisagreementStatus.UNRESOLVED,
    }
)

PHYSICAL_TRANSITIONS: dict[PhysicalStatus, frozenset[PhysicalStatus]] = {
    PhysicalStatus.CREATED: frozenset({PhysicalStatus.SENT}),
    PhysicalStatus.SENT: frozenset({PhysicalStatus.RECEIVED}),
    PhysicalStatus.RECEIVED: frozenset(),
}

EVIDENCE_TRANSITIONS: dict[EvidenceStatus, frozenset[EvidenceStatus]] = {
    EvidenceStatus.PENDING: frozenset({EvidenceStatus.ACCEPTED, EvidenceStatus.DISPUTED}),
    EvidenceStatus.ACCEPTED: frozenset({EvidenceStatus.PENDING}),
    EvidenceStatus.DISPUTED: frozenset({EvidenceStatus.UNDER_REVIEW}),
    EvidenceStatus.UNDER_REVIEW: frozenset(
        {EvidenceStatus.PENDING, EvidenceStatus.UNRESOLVED}
    ),
    EvidenceStatus.UNRESOLVED: frozenset({EvidenceStatus.PENDING}),
}


class DomainRuleViolation(ValueError):
    """Raised when a requested transition would violate a governance rule."""


@dataclass(frozen=True, slots=True)
class RuleDecision:
    allowed: bool
    reason: str | None = None


def _is_present(value: object | None) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def missing_evidence_fields(assessment: AssessmentLike) -> tuple[str, ...]:
    """Return provenance fields that are null, empty, or whitespace-only."""

    return tuple(
        field_name
        for field_name in REQUIRED_PROVENANCE_FIELDS
        if not _is_present(getattr(assessment, field_name, None))
    )


def is_evidence_complete(assessment: AssessmentLike) -> bool:
    return not missing_evidence_fields(assessment)


def derive_completeness(assessment: AssessmentLike) -> CompletenessStatus:
    return (
        CompletenessStatus.COMPLETE
        if is_evidence_complete(assessment)
        else CompletenessStatus.INCOMPLETE
    )


def has_active_disagreement(disagreements: Iterable[DisagreementLike]) -> bool:
    for disagreement in disagreements:
        status = DisagreementStatus(disagreement.status)
        if status in ACTIVE_DISAGREEMENT_STATUSES:
            return True
    return False


def acceptance_decision(
    handover: HandoverLike,
    assessment: AssessmentLike | None,
    disagreements: Iterable[DisagreementLike] = (),
) -> RuleDecision:
    """Evaluate whether the receiver may accept the current evidence version."""

    if assessment is None:
        return RuleDecision(False, "No assessment is available.")
    if not assessment.is_current:
        return RuleDecision(False, "Only the current evidence version can be accepted.")
    if not is_evidence_complete(assessment):
        missing = ", ".join(missing_evidence_fields(assessment))
        return RuleDecision(False, f"Evidence is incomplete: {missing}.")
    status = EvidenceStatus(handover.evidence_status)
    if status is not EvidenceStatus.PENDING:
        return RuleDecision(False, f"Evidence status is {status.value}, not PENDING.")
    if has_active_disagreement(disagreements):
        return RuleDecision(False, "Evidence has an active or unresolved disagreement.")
    return RuleDecision(True)


def can_accept_evidence(
    handover: HandoverLike,
    assessment: AssessmentLike | None,
    disagreements: Iterable[DisagreementLike] = (),
) -> bool:
    return acceptance_decision(handover, assessment, disagreements).allowed


def valid_disagreement(*, reason_type: object | None, responsible_org: str | None) -> bool:
    return bool(reason_type and responsible_org and responsible_org.strip())


def can_transition_physical(
    current: PhysicalStatus | str, target: PhysicalStatus | str
) -> bool:
    current_status = PhysicalStatus(current)
    target_status = PhysicalStatus(target)
    return target_status in PHYSICAL_TRANSITIONS[current_status]


def require_physical_transition(
    current: PhysicalStatus | str, target: PhysicalStatus | str
) -> None:
    if not can_transition_physical(current, target):
        raise DomainRuleViolation(
            f"invalid physical transition: {PhysicalStatus(current).value} -> "
            f"{PhysicalStatus(target).value}"
        )


def can_transition_evidence(
    current: EvidenceStatus | str, target: EvidenceStatus | str
) -> bool:
    current_status = EvidenceStatus(current)
    target_status = EvidenceStatus(target)
    return target_status in EVIDENCE_TRANSITIONS[current_status]


def require_evidence_transition(
    current: EvidenceStatus | str, target: EvidenceStatus | str
) -> None:
    if not can_transition_evidence(current, target):
        raise DomainRuleViolation(
            f"invalid evidence transition: {EvidenceStatus(current).value} -> "
            f"{EvidenceStatus(target).value}"
        )
