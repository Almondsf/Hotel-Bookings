import pyotp
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.models import User

PASSWORD = 'Correct-Horse-Battery-9'


class MfaTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('gm@hotel.com', 'G', 'M', PASSWORD, role='manager')

    def login(self):
        return self.client.post(reverse('login'), {'email': 'gm@hotel.com', 'password': PASSWORD}, format='json')

    def enrol(self):
        self.client.force_authenticate(self.user)
        secret = self.client.post(reverse('mfa-setup')).data['secret']
        codes = self.client.post(reverse('mfa-enable'), {'code': pyotp.TOTP(secret).now()}, format='json').data
        self.client.force_authenticate(None)
        self.user.refresh_from_db()
        return secret, codes['recovery_codes']

    def test_enrolment_needs_a_valid_code(self):
        self.client.force_authenticate(self.user)
        self.client.post(reverse('mfa-setup'))
        self.assertEqual(self.client.post(reverse('mfa-enable'), {'code': '000000'}, format='json').status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)

    def test_two_step_sign_in(self):
        secret, _ = self.enrol()
        first = self.login()
        self.assertTrue(first.data['mfa_required'])
        self.assertNotIn('access', first.data)
        ticket = first.data['mfa_ticket']

        self.assertEqual(self.client.post(reverse('login-mfa'), {'mfa_ticket': ticket, 'code': '123456'}, format='json').status_code, 400)
        # Use the next time step so it's not the one consumed by enrolment
        code = pyotp.TOTP(secret).at(timezone.now().timestamp() + 30)
        second = self.client.post(reverse('login-mfa'), {'mfa_ticket': ticket, 'code': code}, format='json')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertIn('access', second.data)
        # The same code can't be replayed
        replay = self.client.post(reverse('login-mfa'), {'mfa_ticket': self.login().data['mfa_ticket'], 'code': code}, format='json')
        self.assertEqual(replay.status_code, 400)

    def test_recovery_codes_work_once(self):
        _, codes = self.enrol()
        ticket = self.login().data['mfa_ticket']
        ok = self.client.post(reverse('login-mfa'), {'mfa_ticket': ticket, 'recovery_code': codes[0].lower()}, format='json')
        self.assertEqual(ok.status_code, 200)
        again = self.client.post(reverse('login-mfa'), {'mfa_ticket': self.login().data['mfa_ticket'],
                                                        'recovery_code': codes[0]}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_forged_ticket_rejected(self):
        self.enrol()
        response = self.client.post(reverse('login-mfa'), {'mfa_ticket': 'forged', 'code': '123456'}, format='json')
        self.assertEqual(response.status_code, 401)

    @override_settings(ENFORCE_MFA=True)
    def test_enforcement_blocks_unenrolled_privileged_staff(self):
        self.assertFalse(self.user.has_capability('rooms.manage'))
        receptionist = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.assertTrue(receptionist.has_capability('bookings.manage'))  # role not in MFA_REQUIRED_ROLES
        self.enrol()
        self.assertTrue(self.user.has_capability('rooms.manage'))

    def test_required_roles_cannot_switch_it_off(self):
        self.enrol()
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse('mfa-disable'), {'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 403)
