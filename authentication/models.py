from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models

from hotel.fields import EncryptedTextField


def normalize_email(email):
    # Emails are compared case-insensitively everywhere, so store them lowercased.
    return (email or '').strip().lower()


class UserManager(BaseUserManager):
    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        if not first_name:
            raise ValueError('Users must have a first name')
        if not last_name:
            raise ValueError('Users must have a last name')
        user = self.model(email=normalize_email(email), first_name=first_name, last_name=last_name, **extra_fields)
        # No password means an unusable one: the user sets it via an invite link.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, first_name, last_name, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', User.Role.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, first_name, last_name, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD: normalize_email(username)})


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrator'
        MANAGER = 'manager', 'Manager'
        RECEPTIONIST = 'receptionist', 'Receptionist'
        ACCOUNTANT = 'accountant', 'Accountant'
        RESTAURANT = 'restaurant', 'Restaurant Staff'
        BAR = 'bar', 'Bar Staff'
        LAUNDRY = 'laundry', 'Laundry Staff'
        HOUSEKEEPING = 'housekeeping', 'Housekeeping'
        MAINTENANCE = 'maintenance', 'Maintenance'

    email = models.EmailField(unique=True, max_length=255)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RECEPTIONIST)
    phone = models.CharField(
        max_length=20, blank=True,
        validators=[RegexValidator(r'^\+?[0-9 ()-]{7,20}$', 'Enter a valid phone number.')],
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can log into the Django admin site.")

    # Two-factor authentication (TOTP authenticator app)
    mfa_secret = EncryptedTextField(blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_last_step = models.BigIntegerField(default=0, help_text="Last accepted TOTP time step (prevents code replay)")
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def mfa_required(self):
        from django.conf import settings
        return self.is_superuser or self.role in settings.MFA_REQUIRED_ROLES

    def has_capability(self, capability):
        from django.conf import settings

        from authentication.permissions import role_has_capability
        if not self.is_active:
            return False
        if settings.ENFORCE_MFA and self.mfa_required and not self.mfa_enabled:
            return False  # must enrol in two-factor sign-in before doing anything else
        return self.is_superuser or role_has_capability(self.role, capability)

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})" if self.full_name else self.email


class RecoveryCode(models.Model):
    """Single-use backup codes for when the authenticator phone is lost. Stored hashed."""
    user = models.ForeignKey(User, related_name='recovery_codes', on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
