"""
TOTP two-factor sign-in (Google Authenticator, Microsoft Authenticator, Authy).

Sign-in becomes two steps for enrolled users: the password step returns a
short-lived signed "MFA ticket" instead of tokens; the ticket plus a 6-digit
code (or a recovery code) exchanges for tokens.
"""
import hashlib
import secrets

import pyotp
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from .models import RecoveryCode, User

TICKET_SALT = 'authentication.mfa.ticket'
TICKET_MAX_AGE = 300  # seconds to type the code
RECOVERY_CODES = 10


def _hash(code):
    return hashlib.sha256(code.replace('-', '').strip().upper().encode()).hexdigest()


def make_ticket(user):
    return signing.dumps({'uid': user.pk, 'pwd': user.password[-12:]}, salt=TICKET_SALT)


def user_from_ticket(ticket):
    """The user a ticket was issued to, or None if it's forged, expired or the password has changed since."""
    try:
        data = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=data.get('uid'), is_active=True).first()
    return user if user and user.password[-12:] == data.get('pwd') else None


def start_enrolment(user):
    """New secret (not active until confirmed with a code)."""
    user.mfa_secret = pyotp.random_base32()
    user.mfa_enabled = False
    user.save(update_fields=['mfa_secret', 'mfa_enabled'])
    uri = pyotp.TOTP(user.mfa_secret).provisioning_uri(name=user.email, issuer_name=settings.MFA_ISSUER)
    return user.mfa_secret, uri


def verify_code(user, code):
    """Check a TOTP code, accepting one step of clock drift and never the same step twice."""
    code = (code or '').replace(' ', '')
    if not user.mfa_secret or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(user.mfa_secret)
    now = timezone.now()
    for drift in (0, -1, 1):
        at = now.timestamp() + drift * totp.interval
        step = int(at // totp.interval)
        if step > user.mfa_last_step and secrets.compare_digest(totp.at(at), code):
            # Atomic "only if still unused" update: two simultaneous logins can't both use one code
            return User.objects.filter(pk=user.pk, mfa_last_step__lt=step).update(mfa_last_step=step) == 1
    return False


def use_recovery_code(user, code):
    with transaction.atomic():
        match = (RecoveryCode.objects.select_for_update()
                 .filter(user=user, code_hash=_hash(code), used_at__isnull=True).first())
        if match is None:
            return False
        match.used_at = timezone.now()
        match.save(update_fields=['used_at'])
    return True


def confirm_enrolment(user, code):
    """Turn MFA on after the first valid code; returns fresh recovery codes (shown once)."""
    if not verify_code(user, code):
        return None
    with transaction.atomic():
        user.mfa_enabled = True
        user.save(update_fields=['mfa_enabled'])
        return regenerate_recovery_codes(user)


def regenerate_recovery_codes(user):
    user.recovery_codes.all().delete()
    codes = ['-'.join([secrets.token_hex(2).upper(), secrets.token_hex(2).upper()]) for _ in range(RECOVERY_CODES)]
    RecoveryCode.objects.bulk_create(RecoveryCode(user=user, code_hash=_hash(c)) for c in codes)
    return codes


def disable(user):
    user.mfa_enabled = False
    user.mfa_secret = ''
    user.mfa_last_step = 0
    user.save(update_fields=['mfa_enabled', 'mfa_secret', 'mfa_last_step'])
    user.recovery_codes.all().delete()
