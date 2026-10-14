from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Append-only record of security- and business-relevant actions.

    Rows can't be updated or deleted through the ORM. In production the
    application's database role should additionally have only INSERT/SELECT
    on this table.
    """

    class Action(models.TextChoices):
        LOGIN_SUCCEEDED = 'auth.login_succeeded', 'Login succeeded'
        LOGIN_FAILED = 'auth.login_failed', 'Login failed'
        LOGOUT = 'auth.logout', 'Logout'
        PASSWORD_CHANGED = 'auth.password_changed', 'Password changed'
        PASSWORD_RESET_REQUESTED = 'auth.password_reset_requested', 'Password reset requested'
        PASSWORD_RESET_COMPLETED = 'auth.password_reset_completed', 'Password reset completed'
        STAFF_INVITED = 'staff.invited', 'Staff invited'
        STAFF_UPDATED = 'staff.updated', 'Staff updated'
        STAFF_DEACTIVATED = 'staff.deactivated', 'Staff deactivated'
        STAFF_REACTIVATED = 'staff.reactivated', 'Staff reactivated'
        ROOM_TYPE_CREATED = 'rooms.room_type_created', 'Room type created'
        ROOM_CREATED = 'rooms.room_created', 'Room created'
        BOOKING_CREATED = 'bookings.created', 'Booking created'
        BOOKING_MODIFIED = 'bookings.modified', 'Booking modified'
        BOOKING_CHECKED_IN = 'bookings.checked_in', 'Guest checked in'
        BOOKING_CHECKED_OUT = 'bookings.checked_out', 'Guest checked out'
        BOOKING_CANCELLED = 'bookings.cancelled', 'Booking cancelled'
        BOOKING_NO_SHOW = 'bookings.no_show', 'Booking marked no-show'
        BOOKING_HOLD_EXPIRED = 'bookings.hold_expired', 'Booking hold expired'
        BOOKING_ROOM_MOVED = 'bookings.room_moved', 'Booking moved to another room'
        GUEST_UPDATED = 'guests.updated', 'Guest profile updated'
        GUEST_ID_CAPTURED = 'guests.id_captured', 'Guest ID captured'
        GUEST_ID_REVEALED = 'guests.id_revealed', 'Guest ID number revealed'
        FOLIO_OPENED = 'billing.folio_opened', 'Folio opened'
        FOLIO_SETTLED = 'billing.folio_settled', 'Folio settled'
        FOLIO_TRANSFERRED = 'billing.folio_transferred', 'Folio transferred to city ledger'
        CHARGE_POSTED = 'billing.charge_posted', 'Charge posted'
        CHARGE_VOIDED = 'billing.charge_voided', 'Charge voided'
        CHARGE_TRANSFERRED = 'billing.charge_transferred', 'Charge transferred'
        PAYMENT_RECEIVED = 'billing.payment_received', 'Payment received'
        PAYMENT_VOIDED = 'billing.payment_voided', 'Payment voided'
        REFUND_ISSUED = 'billing.refund_issued', 'Refund issued'
        INVOICE_ISSUED = 'billing.invoice_issued', 'Invoice issued'
        ACCOUNT_PAYMENT_RECEIVED = 'billing.account_payment_received', 'City ledger payment received'
        BILLING_CONFIGURED = 'billing.configured', 'Tax rule or exchange rate changed'
        BOOKING_CONFIRMED = 'bookings.confirmed', 'Booking confirmed after payment'
        ONLINE_PAYMENT_SUCCEEDED = 'payments.succeeded', 'Online payment succeeded'
        ONLINE_PAYMENT_REFUNDED = 'payments.refunded', 'Online payment refunded'
        PAYMENT_NEEDS_REVIEW = 'payments.needs_review', 'Online payment needs review'
        PAYMENT_LINK_CREATED = 'payments.link_created', 'Payment link created'
        RATES_CHANGED = 'rates.changed', 'Rate plan, price or restriction changed'
        ROOM_HOUSEKEEPING_CHANGED = 'housekeeping.room_status', 'Room housekeeping status changed'
        HOUSEKEEPING_TASK_UPDATED = 'housekeeping.task', 'Housekeeping task updated'
        MAINTENANCE_TICKET_UPDATED = 'maintenance.ticket', 'Maintenance ticket updated'
        NIGHT_AUDIT_RUN = 'nightaudit.run', 'Night audit run'
        POS_ORDER_SETTLED = 'pos.order_settled', 'POS order settled'
        POS_ORDER_VOIDED = 'pos.order_voided', 'POS order voided'
        CHANNEL_BOOKING_RECEIVED = 'distribution.booking_received', 'OTA booking revision received'
        KEY_ISSUED = 'locks.key_issued', 'Room key issued'
        KEY_REVOKED = 'locks.key_revoked', 'Room key revoked'
        MFA_CHANGED = 'auth.mfa_changed', 'Two-factor sign-in changed'
        GUEST_DATA_EXPORTED = 'privacy.exported', 'Guest data exported'
        GUEST_ANONYMISED = 'privacy.anonymised', 'Guest anonymised'
        RETENTION_APPLIED = 'privacy.retention', 'Retention policy applied'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='audit_events',
    )
    # Snapshot, so the record stays meaningful if the user is renamed or removed,
    # and so failed logins can record the attempted email.
    actor_email = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=64, choices=Action.choices)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['actor', 'created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("Audit log entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit log entries cannot be deleted.")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email or 'anonymous'} {self.action}"
