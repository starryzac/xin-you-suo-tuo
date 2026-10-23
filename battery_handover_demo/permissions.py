"""Role permissions and organization-scope checks."""

from __future__ import annotations

from enum import Enum

from .models import UserRole


class PermissionAction(str, Enum):
    VIEW_BATTERY_LIST = "VIEW_BATTERY_LIST"
    VIEW_BATTERY_DETAIL = "VIEW_BATTERY_DETAIL"
    CREATE_HANDOVER = "CREATE_HANDOVER"
    SUBMIT_ASSESSMENT = "SUBMIT_ASSESSMENT"
    VIEW_OWN_HANDOVER = "VIEW_OWN_HANDOVER"
    VIEW_DISAGREEMENT = "VIEW_DISAGREEMENT"
    PROVIDE_EVIDENCE = "PROVIDE_EVIDENCE"
    CONFIRM_PHYSICAL_RECEIPT = "CONFIRM_PHYSICAL_RECEIPT"
    ACCEPT_EVIDENCE = "ACCEPT_EVIDENCE"
    RAISE_DISAGREEMENT = "RAISE_DISAGREEMENT"
    VIEW_CURRENT_EVIDENCE = "VIEW_CURRENT_EVIDENCE"
    VIEW_CORRECTION_HISTORY = "VIEW_CORRECTION_HISTORY"
    VIEW_EVIDENCE = "VIEW_EVIDENCE"
    APPLY_CORRECTION = "APPLY_CORRECTION"
    START_REVIEW = "START_REVIEW"
    SUBMIT_REVIEW_OUTCOME = "SUBMIT_REVIEW_OUTCOME"
    VIEW_AUDIT_TRAIL = "VIEW_AUDIT_TRAIL"
    VIEW_ALL_DISAGREEMENTS = "VIEW_ALL_DISAGREEMENTS"
    VIEW_ALL_CORRECTIONS = "VIEW_ALL_CORRECTIONS"
    VIEW_ALL_VERSIONS = "VIEW_ALL_VERSIONS"


COMMON_READ_ACTIONS = frozenset(
    {PermissionAction.VIEW_BATTERY_LIST, PermissionAction.VIEW_BATTERY_DETAIL}
)

ROLE_PERMISSIONS: dict[UserRole, frozenset[PermissionAction]] = {
    UserRole.SENDER: COMMON_READ_ACTIONS
    | frozenset(
        {
            PermissionAction.CREATE_HANDOVER,
            PermissionAction.SUBMIT_ASSESSMENT,
            PermissionAction.VIEW_OWN_HANDOVER,
            PermissionAction.VIEW_DISAGREEMENT,
            PermissionAction.PROVIDE_EVIDENCE,
        }
    ),
    UserRole.RECEIVER: COMMON_READ_ACTIONS
    | frozenset(
        {
            PermissionAction.CONFIRM_PHYSICAL_RECEIPT,
            PermissionAction.ACCEPT_EVIDENCE,
            PermissionAction.RAISE_DISAGREEMENT,
            PermissionAction.VIEW_CURRENT_EVIDENCE,
            PermissionAction.VIEW_CORRECTION_HISTORY,
        }
    ),
    UserRole.REVIEWER: COMMON_READ_ACTIONS
    | frozenset(
        {
            PermissionAction.VIEW_EVIDENCE,
            PermissionAction.VIEW_DISAGREEMENT,
            PermissionAction.APPLY_CORRECTION,
            PermissionAction.START_REVIEW,
            PermissionAction.SUBMIT_REVIEW_OUTCOME,
        }
    ),
    UserRole.REGULATOR: COMMON_READ_ACTIONS
    | frozenset(
        {
            PermissionAction.VIEW_AUDIT_TRAIL,
            PermissionAction.VIEW_ALL_DISAGREEMENTS,
            PermissionAction.VIEW_ALL_CORRECTIONS,
            PermissionAction.VIEW_ALL_VERSIONS,
        }
    ),
}


class PermissionDenied(PermissionError):
    """Raised when a role or organization scope forbids an action."""


def _coerce_role(role: UserRole | str) -> UserRole:
    return role if isinstance(role, UserRole) else UserRole(role)


def _coerce_action(action: PermissionAction | str) -> PermissionAction:
    return action if isinstance(action, PermissionAction) else PermissionAction(action)


def has_permission(role: UserRole | str, action: PermissionAction | str) -> bool:
    normalized_role = _coerce_role(role)
    normalized_action = _coerce_action(action)
    return normalized_action in ROLE_PERMISSIONS[normalized_role]


def require_permission(role: UserRole | str, action: PermissionAction | str) -> None:
    if not has_permission(role, action):
        raise PermissionDenied(f"{_coerce_role(role).value} cannot {_coerce_action(action).value}")


def has_handover_scope(
    role: UserRole | str,
    organization: str,
    *,
    sender_org: str,
    receiver_org: str,
) -> bool:
    """Return whether an actor may see a handover in its organization scope."""

    normalized_role = _coerce_role(role)
    if normalized_role in {UserRole.REVIEWER, UserRole.REGULATOR}:
        return True
    if normalized_role is UserRole.SENDER:
        return organization == sender_org
    if normalized_role is UserRole.RECEIVER:
        return organization == receiver_org
    return False


def require_handover_scope(
    role: UserRole | str,
    organization: str,
    *,
    sender_org: str,
    receiver_org: str,
) -> None:
    if not has_handover_scope(
        role,
        organization,
        sender_org=sender_org,
        receiver_org=receiver_org,
    ):
        raise PermissionDenied("actor cannot access records belonging to another organization")
