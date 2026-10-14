"""
Door-lock systems. Hotels' lock servers (ASSA ABLOY Visionline, Salto Space,
Onity...) run on the property; lock vendors or their integrators expose them
over a local HTTP bridge. LOCK_SYSTEM selects the adapter:

  'none'   record keys only (mechanical / standalone locks)
  'bridge' an on-premise HTTP bridge at LOCK_BRIDGE_URL, requests signed with
           LOCK_BRIDGE_SECRET (HMAC-SHA256 of the body, header X-Signature)
"""
import hashlib
import hmac
import json
import uuid

import requests
from django.conf import settings

from hotel.errors import DomainError


class LockSystemError(DomainError):
    status_code = 502


class RecordOnlyLockSystem:
    """For hotels without electronic locks: keeps the key register, encodes nothing."""

    def issue(self, *, room_number, valid_from, valid_until, guest_name, cards):
        return [f"manual-{uuid.uuid4().hex[:12]}" for _ in range(cards)]

    def revoke(self, external_id):
        return None


class BridgeLockSystem:
    timeout = 15

    def _post(self, path, payload):
        body = json.dumps(payload, default=str).encode()
        signature = hmac.new(settings.LOCK_BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
        try:
            response = requests.post(f"{settings.LOCK_BRIDGE_URL.rstrip('/')}{path}", data=body, timeout=self.timeout,
                                     headers={'Content-Type': 'application/json', 'X-Signature': signature})
        except requests.RequestException as e:
            raise LockSystemError(f"Lock server unreachable: {e.__class__.__name__}. Is the encoder online?")
        if response.status_code >= 400:
            raise LockSystemError(f"Lock server refused the request ({response.status_code}).")
        return response.json() if response.content else {}

    def issue(self, *, room_number, valid_from, valid_until, guest_name, cards):
        result = self._post('/keys', {'room': room_number, 'valid_from': valid_from, 'valid_until': valid_until,
                                      'guest_name': guest_name, 'cards': cards})
        return [str(key) for key in result.get('key_ids', [])]

    def revoke(self, external_id):
        self._post(f'/keys/{external_id}/revoke', {})


def lock_system():
    if settings.LOCK_SYSTEM == 'bridge':
        if not settings.LOCK_BRIDGE_URL or not settings.LOCK_BRIDGE_SECRET:
            raise LockSystemError("The lock bridge is not configured.")
        return BridgeLockSystem()
    return RecordOnlyLockSystem()
