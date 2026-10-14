"""
Encrypted model fields for sensitive personal data (ID numbers etc.).

Values are encrypted with Fernet (AES-128-CBC + HMAC) using
settings.FIELD_ENCRYPTION_KEYS. The first key encrypts; all keys decrypt, so
keys can be rotated by prepending a new one and re-saving rows.

Encrypted values are non-deterministic, so these fields can't be filtered or
indexed. Store a non-sensitive companion (e.g. last 4 digits) for lookups.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@lru_cache(maxsize=1)
def _fernet(keys):
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is not set.")
    return MultiFernet([Fernet(key) for key in keys])


def fernet():
    return _fernet(tuple(settings.FIELD_ENCRYPTION_KEYS))


def encrypt(value):
    return fernet().encrypt(value.encode()).decode()


def decrypt(token):
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ImproperlyConfigured("Could not decrypt a field: wrong or missing FIELD_ENCRYPTION_KEYS.")


class EncryptedTextField(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '':
            return value
        return encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        return decrypt(value)

    def get_lookup(self, lookup_name):
        if lookup_name not in ('isnull',):
            raise TypeError("Encrypted fields can't be filtered on; use a companion field.")
        return super().get_lookup(lookup_name)
