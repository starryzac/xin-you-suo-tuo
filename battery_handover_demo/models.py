"""Relational data model for the handover-accountability workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for audit fields."""

    return datetime.now(UTC)


class StrEnum(str, Enum):
    """Enum whose values serialize as the strings shown in the specification."""


class UserRole(StrEnum):
    SENDER = "SENDER"
    RECEIVER = "RECEIVER"
    REVIEWER = "REVIEWER"
    REGULATOR = "REGULATOR"


class PhysicalStatus(StrEnum):
    CREATED = "CREATED"
    SENT = "SENT"
    RECEIVED = "RECEIVED"


class EvidenceStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UNRESOLVED = "UNRESOLVED"


class CompletenessStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class DisagreementReasonType(StrEnum):
    MISSING_DATE = "MISSING_DATE"
    MISSING_METHOD = "MISSING_METHOD"
    MISSING_PROVIDER = "MISSING_PROVIDER"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    CONDITION_CONFLICT = "CONDITION_CONFLICT"
    ACCESS_CONCERN = "ACCESS_CONCERN"
    OTHER = "OTHER"


class DisagreementStatus(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


def enum_column(enum_type: type[StrEnum], name: str) -> SqlEnum:
    """Build a portable string enum with a database CHECK constraint."""

    return SqlEnum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("trim(username) <> ''", name="ck_users_username_nonempty"),
        CheckConstraint("trim(organization) <> ''", name="ck_users_organization_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    organization: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, "user_role"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    created_handovers: Mapped[list[Handover]] = relationship(
        back_populates="creator", foreign_keys="Handover.created_by"
    )
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="creator", foreign_keys="Assessment.created_by"
    )
    disagreements: Mapped[list[Disagreement]] = relationship(
        back_populates="raiser", foreign_keys="Disagreement.raised_by"
    )
    corrections: Mapped[list[Correction]] = relationship(
        back_populates="corrector", foreign_keys="Correction.corrected_by"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="user")


class Battery(Base):
    __tablename__ = "batteries"
    __table_args__ = (
        UniqueConstraint("battery_id", name="uq_batteries_battery_id"),
        CheckConstraint("trim(battery_id) <> ''", name="ck_batteries_battery_id_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Public/business identifier. Other tables reference ``id`` through a
    # distinctly named ``battery_pk`` column so business IDs are never FKs.
    battery_id: Mapped[str] = mapped_column(String(100), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(160), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    current_holder: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    handovers: Mapped[list[Handover]] = relationship(back_populates="battery")
    assessments: Mapped[list[Assessment]] = relationship(back_populates="battery")


class Handover(Base):
    __tablename__ = "handovers"
    __table_args__ = (
        CheckConstraint("trim(sender_org) <> ''", name="ck_handovers_sender_nonempty"),
        CheckConstraint("trim(receiver_org) <> ''", name="ck_handovers_receiver_nonempty"),
        Index("ix_handovers_statuses", "physical_status", "evidence_status", "completeness_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battery_pk: Mapped[int] = mapped_column(
        ForeignKey("batteries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sender_org: Mapped[str] = mapped_column(String(160), nullable=False)
    receiver_org: Mapped[str] = mapped_column(String(160), nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    physical_status: Mapped[PhysicalStatus] = mapped_column(
        enum_column(PhysicalStatus, "physical_status"),
        nullable=False,
        default=PhysicalStatus.CREATED,
    )
    evidence_status: Mapped[EvidenceStatus] = mapped_column(
        enum_column(EvidenceStatus, "evidence_status"),
        nullable=False,
        default=EvidenceStatus.PENDING,
    )
    completeness_status: Mapped[CompletenessStatus] = mapped_column(
        enum_column(CompletenessStatus, "completeness_status"),
        nullable=False,
        default=CompletenessStatus.INCOMPLETE,
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    battery: Mapped[Battery] = relationship(back_populates="handovers")
    creator: Mapped[User] = relationship(
        back_populates="created_handovers", foreign_keys=[created_by]
    )
    assessments: Mapped[list[Assessment]] = relationship(back_populates="handover")
    disagreements: Mapped[list[Disagreement]] = relationship(back_populates="handover")


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("handover_id", "version", name="uq_assessments_handover_version"),
        CheckConstraint("version >= 1", name="ck_assessments_version_positive"),
        CheckConstraint(
            "trim(condition_statement) <> ''",
            name="ck_assessments_condition_nonempty",
        ),
        Index("ix_assessments_current", "handover_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    handover_id: Mapped[int] = mapped_column(
        ForeignKey("handovers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    battery_pk: Mapped[int] = mapped_column(
        ForeignKey("batteries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    condition_statement: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assessment_method: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_org: Mapped[str | None] = mapped_column(String(160), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    handover: Mapped[Handover] = relationship(back_populates="assessments")
    battery: Mapped[Battery] = relationship(back_populates="assessments")
    creator: Mapped[User] = relationship(back_populates="assessments", foreign_keys=[created_by])
    disagreements: Mapped[list[Disagreement]] = relationship(back_populates="assessment")
    corrections: Mapped[list[Correction]] = relationship(back_populates="assessment")


class Disagreement(Base):
    __tablename__ = "disagreements"
    __table_args__ = (
        CheckConstraint(
            "trim(responsible_org) <> ''",
            name="ck_disagreements_responsible_org_nonempty",
        ),
        Index("ix_disagreements_handover_status", "handover_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    handover_id: Mapped[int] = mapped_column(
        ForeignKey("handovers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    raised_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason_type: Mapped[DisagreementReasonType] = mapped_column(
        enum_column(DisagreementReasonType, "disagreement_reason_type"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_org: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[DisagreementStatus] = mapped_column(
        enum_column(DisagreementStatus, "disagreement_status"),
        nullable=False,
        default=DisagreementStatus.OPEN,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    handover: Mapped[Handover] = relationship(back_populates="disagreements")
    assessment: Mapped[Assessment] = relationship(back_populates="disagreements")
    raiser: Mapped[User] = relationship(back_populates="disagreements", foreign_keys=[raised_by])


class Correction(Base):
    __tablename__ = "corrections"
    __table_args__ = (
        CheckConstraint("trim(field_name) <> ''", name="ck_corrections_field_nonempty"),
        CheckConstraint("trim(reason) <> ''", name="ck_corrections_reason_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # References the source assessment version; the service creates a new
    # Assessment row rather than changing the source row's business values.
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    assessment: Mapped[Assessment] = relationship(back_populates="corrections")
    corrector: Mapped[User] = relationship(back_populates="corrections", foreign_keys=[corrected_by])


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("trim(action) <> ''", name="ck_audit_events_action_nonempty"),
        CheckConstraint("trim(target_type) <> ''", name="ck_audit_events_target_type_nonempty"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="audit_events")
