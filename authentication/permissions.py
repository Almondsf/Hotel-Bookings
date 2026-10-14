"""
Role-based access control.

Views check *capabilities*, never role names, so what each role may do is
defined in exactly one place: CAPABILITIES below. The admin role (and
superusers) implicitly hold every capability.
"""
from rest_framework.permissions import BasePermission

from authentication.models import User

Role = User.Role

CAPABILITIES = {
    'rooms.manage': {Role.MANAGER},
    'staff.manage': {Role.MANAGER},
    'audit.view': {Role.MANAGER},
    'bookings.view': {Role.MANAGER, Role.RECEPTIONIST, Role.ACCOUNTANT},
    'bookings.manage': {Role.MANAGER, Role.RECEPTIONIST},
    # Full ID document numbers (masked everywhere else)
    'guests.view_identity': {Role.MANAGER},
    'folios.view': {Role.MANAGER, Role.RECEPTIONIST, Role.ACCOUNTANT},
    'folios.post': {Role.MANAGER, Role.RECEPTIONIST, Role.ACCOUNTANT},
    # Voids, allowances, charge transfers: corrections that reduce revenue
    'folios.adjust': {Role.MANAGER, Role.ACCOUNTANT},
    'payments.take': {Role.MANAGER, Role.RECEPTIONIST, Role.ACCOUNTANT},
    'payments.refund': {Role.MANAGER, Role.ACCOUNTANT},
    'accounts.manage': {Role.MANAGER, Role.ACCOUNTANT},
    # Tax rules and exchange rates
    'billing.configure': {Role.MANAGER, Role.ACCOUNTANT},
    'rates.manage': {Role.MANAGER},
    'housekeeping.view': {Role.MANAGER, Role.RECEPTIONIST, Role.HOUSEKEEPING},
    # Start / complete cleaning tasks
    'housekeeping.work': {Role.MANAGER, Role.HOUSEKEEPING},
    # Generate and assign tasks, inspect rooms, set room status
    'housekeeping.manage': {Role.MANAGER},
    'maintenance.view': {Role.MANAGER, Role.RECEPTIONIST, Role.HOUSEKEEPING, Role.MAINTENANCE},
    # Any staff member can report a fault
    'maintenance.report': {Role.MANAGER, Role.RECEPTIONIST, Role.ACCOUNTANT, Role.RESTAURANT, Role.BAR,
                           Role.LAUNDRY, Role.HOUSEKEEPING, Role.MAINTENANCE},
    'maintenance.manage': {Role.MANAGER, Role.MAINTENANCE},
    'reports.view': {Role.MANAGER, Role.ACCOUNTANT},
    # Selling at outlets (each outlet also limits which roles may use it)
    'pos.use': {Role.MANAGER, Role.RECEPTIONIST, Role.RESTAURANT, Role.BAR, Role.LAUNDRY, Role.HOUSEKEEPING},
    'pos.manage': {Role.MANAGER},
    'pos.void': {Role.MANAGER},
    # Guest data export and erasure (NDPA requests)
    'privacy.manage': {Role.MANAGER},
    # Closing the day is usually the night receptionist's job
    'night_audit.run': {Role.MANAGER, Role.ACCOUNTANT, Role.RECEPTIONIST},
    # Agree a custom nightly rate on a booking
    'rates.override': {Role.MANAGER},
}

# Roles only an administrator may grant or manage. Stops a manager from
# creating a peer or promoting someone to their own level or above.
PRIVILEGED_ROLES = {Role.ADMIN, Role.MANAGER}


def role_has_capability(role, capability):
    if capability not in CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability}")
    return role == Role.ADMIN or role in CAPABILITIES[capability]


def capabilities_for(user):
    return sorted(c for c in CAPABILITIES if user.has_capability(c))


def is_administrator(user):
    return user.is_superuser or user.role == Role.ADMIN


def can_assign_role(actor, role):
    return is_administrator(actor) or role not in PRIVILEGED_ROLES


def can_manage_user(actor, target):
    """Whether `actor` may edit, deactivate or reactivate `target`."""
    if actor.pk == target.pk:
        return False  # role/status changes on yourself must go through someone else
    if target.is_superuser:
        return actor.is_superuser
    return can_assign_role(actor, target.role)


def HasCapability(capability):
    """DRF permission class requiring the given capability, e.g. HasCapability('rooms.manage')."""
    if capability not in CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability}")

    class _HasCapability(BasePermission):
        def has_permission(self, request, view):
            user = request.user
            return bool(user and user.is_authenticated and user.has_capability(capability))

    _HasCapability.__name__ = f"HasCapability[{capability}]"
    return _HasCapability
