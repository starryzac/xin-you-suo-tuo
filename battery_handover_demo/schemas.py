"""Dependency-light command schemas used by the service layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import DisagreementReasonType, UserRole


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: int
    organization: str
    role: UserRole

    def __post_init__(self) -> None:
        if self.user_id < 1:
            raise ValueError("user_id must be positive")
        object.__setattr__(self, "organization", _require_text(self.organization, "organization"))


@dataclass(frozen=True, slots=True)
class UserCreate:
    username: str
    organization: str
    role: UserRole

    def __post_init__(self) -> None:
        object.__setattr__(self, "username", _require_text(self.username, "username"))
        object.__setattr__(self, "organization", _require_text(self.organization, "organization"))


@dataclass(frozen=True, slots=True)
class BatteryCreate:
    battery_id: str
    manufacturer: str
    model: str
    current_holder: str
    lifecycle_status: str

    def __post_init__(self) -> None:
        for field_name in (
            "battery_id",
            "manufacturer",
            "model",
            "current_holder",
            "lifecycle_status",
        ):
            object.__setattr__(self, field_name, _require_text(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class HandoverCreate:
    battery_pk: int
    sender_org: str
    receiver_org: str
    transfer_date: date

    def __post_init__(self) -> None:
        if self.battery_pk < 1:
            raise ValueError("battery_pk must be positive")
        object.__setattr__(self, "sender_org", _require_text(self.sender_org, "sender_org"))
        object.__setattr__(self, "receiver_org", _require_text(self.receiver_org, "receiver_org"))


@dataclass(frozen=True, slots=True)
class AssessmentCreate:
    handover_id: int
    battery_pk: int
    condition_statement: str
    assessment_date: date | None = None
    assessment_method: str | None = None
    provider_org: str | None = None
    evidence_reference: str | None = None

    def __post_init__(self) -> None:
        if self.handover_id < 1:
            raise ValueError("handover_id must be positive")
        if self.battery_pk < 1:
            raise ValueError("battery_pk must be positive")
        object.__setattr__(
            self,
            "condition_statement",
            _require_text(self.condition_statement, "condition_statement"),
        )
        for field_name in ("assessment_method", "provider_org", "evidence_reference"):
            object.__setattr__(self, field_name, _optional_text(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class DisagreementCreate:
    handover_id: int
    assessment_id: int
    reason_type: DisagreementReasonType
    responsible_org: str
    description: str | None = None

    def __post_init__(self) -> None:
        if self.handover_id < 1:
            raise ValueError("handover_id must be positive")
        if self.assessment_id < 1:
            raise ValueError("assessment_id must be positive")
        object.__setattr__(
            self,
            "responsible_org",
            _require_text(self.responsible_org, "responsible_org"),
        )
        object.__setattr__(self, "description", _optional_text(self.description))


@dataclass(frozen=True, slots=True)
class CorrectionCreate:
    assessment_id: int
    field_name: str
    new_value: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.assessment_id < 1:
            raise ValueError("assessment_id must be positive")
        object.__setattr__(self, "field_name", _require_text(self.field_name, "field_name"))
        object.__setattr__(self, "new_value", _optional_text(self.new_value))
        object.__setattr__(self, "reason", _require_text(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class AuditEventCreate:
    action: str
    target_type: str
    target_id: int
    success: bool
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.target_id < 1:
            raise ValueError("target_id must be positive")
        object.__setattr__(self, "action", _require_text(self.action, "action"))
        object.__setattr__(self, "target_type", _require_text(self.target_type, "target_type"))
        for field_name in ("old_value", "new_value", "reason"):
            object.__setattr__(self, field_name, _optional_text(getattr(self, field_name)))
