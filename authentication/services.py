import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User

logger = logging.getLogger(__name__)


def revoke_all_sessions(user):
    """
    Blacklist every refresh token issued to `user`, signing them out
    everywhere. Short-lived access tokens expire on their own.
    """
    tokens = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create((BlacklistedToken(token=token) for token in tokens), ignore_conflicts=True)


def build_set_password_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/set-password?uid={uid}&token={token}"


def user_from_reset_token(uid, token):
    """Return the user the (uid, token) pair is valid for, or None."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user


def _send(user, subject, message):
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception:
        logger.exception("Failed to send '%s' email to user %s", subject, user.pk)


def send_staff_invite(user, invited_by):
    _send(user, "You've been invited to the hotel staff portal", f"""
Hello {user.first_name},

{invited_by.full_name} has created a staff account for you ({user.get_role_display()}).

Set your password here to get started:
{build_set_password_link(user)}

This link expires in {settings.PASSWORD_RESET_TIMEOUT // 3600} hours and can only be used once.
""")


def send_password_reset(user):
    _send(user, "Reset your password", f"""
Hello {user.first_name},

Someone requested a password reset for your staff account. If this was you,
set a new password here:
{build_set_password_link(user)}

This link expires in {settings.PASSWORD_RESET_TIMEOUT // 3600} hours. If you did not
request this, you can ignore this email.
""")
