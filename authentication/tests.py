import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from authentication.permissions import HasCapability, can_assign_role, role_has_capability

PASSWORD = 'Correct-Horse-Battery-9'


def make_user(email, role=User.Role.RECEPTIONIST, **extra):
    return User.objects.create_user(email, 'Test', role.title(), PASSWORD, role=role, **extra)


def extract_link_params(body):
    match = re.search(r'set-password\?uid=([^&\s]+)&token=(\S+)', body)
    return {'uid': match.group(1), 'token': match.group(2)}


class AuthTestCase(APITestCase):
    def setUp(self):
        cache.clear()  # reset throttle counters

    def login(self, email, password=PASSWORD, **extra):
        return self.client.post(reverse('login'), {'email': email, 'password': password}, format='json', **extra)

    def bearer(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')


class LoginTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user('ada@hotel.com')

    def test_login_returns_tokens_user_and_capabilities(self):
        response = self.login('ADA@Hotel.com ')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['role'], 'receptionist')
        self.assertIn('bookings.manage', response.data['user']['capabilities'])
        self.assertNotIn('staff.manage', response.data['user']['capabilities'])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.LOGIN_SUCCEEDED, actor=self.user).exists())

    def test_wrong_password_is_rejected_and_audited(self):
        response = self.login('ada@hotel.com', 'wrong')
        self.assertEqual(response.status_code, 401)
        entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
        self.assertEqual(entry.actor_email, 'ada@hotel.com')
        self.assertIsNone(entry.actor)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login('ada@hotel.com').status_code, 401)

    def test_invited_user_without_password_cannot_log_in(self):
        User.objects.create_user('new@hotel.com', 'New', 'Person', None)
        self.assertEqual(self.login('new@hotel.com', '').status_code, 400)
        self.assertEqual(self.login('new@hotel.com', 'anything').status_code, 401)

    def test_login_throttled_per_account_across_ips(self):
        statuses = [
            self.login('ada@hotel.com', 'wrong', REMOTE_ADDR=f'10.0.0.{i}').status_code
            for i in range(12)
        ]
        self.assertIn(429, statuses)

    def test_refresh_token_rotation_blacklists_old_token(self):
        refresh = self.login('ada@hotel.com').data['refresh']
        first = self.client.post(reverse('token-refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(first.status_code, 200)
        reused = self.client.post(reverse('token-refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(reused.status_code, 401)

    def test_logout_revokes_refresh_token(self):
        tokens = self.login('ada@hotel.com').data
        self.bearer(tokens['access'])
        self.assertEqual(self.client.post(reverse('logout'), {'refresh': tokens['refresh']}, format='json').status_code, 205)
        self.assertEqual(self.client.post(reverse('token-refresh'), {'refresh': tokens['refresh']}, format='json').status_code, 401)

    def test_cannot_log_out_someone_elses_session(self):
        make_user('other@hotel.com')
        other_refresh = self.login('other@hotel.com').data['refresh']
        self.bearer(self.login('ada@hotel.com').data['access'])
        self.assertEqual(self.client.post(reverse('logout'), {'refresh': other_refresh}, format='json').status_code, 400)

    def test_me(self):
        self.bearer(self.login('ada@hotel.com').data['access'])
        response = self.client.get(reverse('me'))
        self.assertEqual(response.data['email'], 'ada@hotel.com')
        self.client.credentials()
        self.assertEqual(self.client.get(reverse('me')).status_code, 401)


class PasswordTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user('ada@hotel.com')

    def test_change_password_requires_current_password_and_revokes_sessions(self):
        tokens = self.login('ada@hotel.com').data
        self.bearer(tokens['access'])
        url = reverse('change-password')

        wrong = self.client.post(url, {'current_password': 'nope', 'new_password': 'New-Strong-Pass-42'}, format='json')
        self.assertEqual(wrong.status_code, 400)
        weak = self.client.post(url, {'current_password': PASSWORD, 'new_password': '123'}, format='json')
        self.assertEqual(weak.status_code, 400)

        ok = self.client.post(url, {'current_password': PASSWORD, 'new_password': 'New-Strong-Pass-42'}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.post(reverse('token-refresh'), {'refresh': tokens['refresh']}, format='json').status_code, 401)
        self.assertEqual(self.login('ada@hotel.com', 'New-Strong-Pass-42').status_code, 200)

    def test_reset_response_is_identical_for_unknown_email(self):
        known = self.client.post(reverse('password-reset'), {'email': 'ada@hotel.com'}, format='json')
        unknown = self.client.post(reverse('password-reset'), {'email': 'ghost@hotel.com'}, format='json')
        self.assertEqual((known.status_code, known.data), (unknown.status_code, unknown.data))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ada@hotel.com'])

    def test_reset_link_sets_password_once(self):
        self.client.post(reverse('password-reset'), {'email': 'ada@hotel.com'}, format='json')
        params = extract_link_params(mail.outbox[0].body)
        url = reverse('password-reset-confirm')

        first = self.client.post(url, {**params, 'new_password': 'Reset-Strong-Pass-7'}, format='json')
        self.assertEqual(first.status_code, 200, first.data)
        again = self.client.post(url, {**params, 'new_password': 'Another-Strong-Pass-8'}, format='json')
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self.login('ada@hotel.com', 'Reset-Strong-Pass-7').status_code, 200)

    def test_reset_with_garbage_token(self):
        response = self.client.post(reverse('password-reset-confirm'), {
            'uid': 'zzz', 'token': 'nope', 'new_password': 'Reset-Strong-Pass-7',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class StaffManagementTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user('admin@hotel.com', User.Role.ADMIN)
        self.manager = make_user('manager@hotel.com', User.Role.MANAGER)
        self.receptionist = make_user('desk@hotel.com', User.Role.RECEPTIONIST)

    def act_as(self, user):
        self.client.force_authenticate(user)

    def invite(self, role, email='new@hotel.com', **extra):
        return self.client.post(reverse('staff-list'), {
            'email': email, 'first_name': 'New', 'last_name': 'Hire', 'role': role, **extra,
        }, format='json')

    def test_non_managers_cannot_access_staff(self):
        self.act_as(self.receptionist)
        self.assertEqual(self.client.get(reverse('staff-list')).status_code, 403)
        self.assertEqual(self.invite('receptionist').status_code, 403)

    def test_manager_invites_staff_who_then_sets_password(self):
        self.act_as(self.manager)
        response = self.invite('housekeeping', email='New@Hotel.com', is_staff=True, is_superuser=True)
        self.assertEqual(response.status_code, 201, response.data)

        user = User.objects.get(email='new@hotel.com')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.STAFF_INVITED, target_id=str(user.pk)).exists())

        params = extract_link_params(mail.outbox[0].body)
        self.client.force_authenticate(None)
        self.client.post(reverse('password-reset-confirm'), {**params, 'new_password': 'Invite-Strong-Pass-3'}, format='json')
        self.assertEqual(self.login('new@hotel.com', 'Invite-Strong-Pass-3').status_code, 200)

    def test_manager_cannot_create_or_promote_privileged_roles(self):
        self.act_as(self.manager)
        self.assertEqual(self.invite('manager').status_code, 400)
        self.assertEqual(self.invite('admin').status_code, 400)
        url = reverse('staff-detail', args=[self.receptionist.pk])
        self.assertEqual(self.client.patch(url, {'role': 'manager'}, format='json').status_code, 400)

    def test_manager_cannot_manage_admins_or_peers(self):
        self.act_as(self.manager)
        other_manager = make_user('m2@hotel.com', User.Role.MANAGER)
        for target in [self.admin, other_manager]:
            self.assertEqual(
                self.client.patch(reverse('staff-detail', args=[target.pk]), {'first_name': 'X'}, format='json').status_code,
                403,
            )
            self.assertEqual(self.client.post(reverse('staff-deactivate', args=[target.pk])).status_code, 403)

    def test_nobody_can_change_or_deactivate_themselves(self):
        self.act_as(self.admin)
        self.assertEqual(
            self.client.patch(reverse('staff-detail', args=[self.admin.pk]), {'role': 'receptionist'}, format='json').status_code,
            403,
        )
        self.assertEqual(self.client.post(reverse('staff-deactivate', args=[self.admin.pk])).status_code, 403)

    def test_admin_can_create_manager(self):
        self.act_as(self.admin)
        self.assertEqual(self.invite('manager').status_code, 201)

    def test_role_change_is_audited_and_takes_effect(self):
        self.act_as(self.manager)
        url = reverse('staff-detail', args=[self.receptionist.pk])
        self.assertEqual(self.client.patch(url, {'role': 'accountant'}, format='json').status_code, 200)
        entry = AuditLog.objects.get(action=AuditLog.Action.STAFF_UPDATED)
        self.assertEqual(entry.changes, {'role': {'from': 'receptionist', 'to': 'accountant'}})
        self.assertEqual(entry.actor, self.manager)

    def test_deactivation_blocks_existing_tokens(self):
        tokens = self.login('desk@hotel.com').data
        self.act_as(self.manager)
        self.assertEqual(self.client.post(reverse('staff-deactivate', args=[self.receptionist.pk])).status_code, 200)
        self.client.force_authenticate(None)

        self.bearer(tokens['access'])
        self.assertEqual(self.client.get(reverse('me')).status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post(reverse('token-refresh'), {'refresh': tokens['refresh']}, format='json').status_code, 401)

    def test_staff_cannot_be_deleted(self):
        self.act_as(self.admin)
        self.assertEqual(self.client.delete(reverse('staff-detail', args=[self.receptionist.pk])).status_code, 405)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.act_as(self.manager)
        self.assertEqual(self.invite('receptionist', email='DESK@hotel.com').status_code, 400)


class PermissionModelTests(TestCase):
    def test_admin_role_has_every_capability(self):
        self.assertTrue(role_has_capability(User.Role.ADMIN, 'audit.view'))

    def test_unknown_capability_fails_loudly(self):
        with self.assertRaises(ValueError):
            HasCapability('rooms.mange')
        with self.assertRaises(ValueError):
            role_has_capability(User.Role.MANAGER, 'nope')

    def test_inactive_user_has_no_capabilities(self):
        user = make_user('x@hotel.com', User.Role.MANAGER, is_active=False)
        self.assertFalse(user.has_capability('rooms.manage'))

    def test_manager_role_assignment(self):
        manager = make_user('m@hotel.com', User.Role.MANAGER)
        self.assertTrue(can_assign_role(manager, User.Role.BAR))
        self.assertFalse(can_assign_role(manager, User.Role.MANAGER))


class BrowserCookieSessionTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        make_user('ada@hotel.com')

    def test_refresh_token_lives_only_in_httponly_cookie(self):
        response = self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('refresh', response.data)
        cookie = response.cookies['hotel_refresh']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(cookie['path'], '/api/auth/')

        first = self.client.post(reverse('token-refresh'), {}, format='json')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertIn('access', first.data)
        self.assertNotIn('refresh', first.data)
        self.assertNotEqual(first.cookies['hotel_refresh'].value, cookie.value)  # rotated

    def test_logout_clears_cookie_and_revokes(self):
        tokens = self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie').data
        old_cookie = self.client.cookies['hotel_refresh'].value
        self.bearer(tokens['access'])
        response = self.client.post(reverse('logout'), {}, format='json')
        self.assertEqual(response.status_code, 205)
        self.assertEqual(response.cookies['hotel_refresh'].value, '')
        self.client.credentials()
        self.client.cookies['hotel_refresh'] = old_cookie
        self.assertEqual(self.client.post(reverse('token-refresh'), {}, format='json').status_code, 401)

    def test_refresh_without_any_token(self):
        self.assertEqual(self.client.post(reverse('token-refresh'), {}, format='json').status_code, 401)

    def test_quick_double_refresh_does_not_sign_out(self):
        """Two page loads sending the same cookie moments apart both stay signed in, with the same new token."""
        self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie')
        old = self.client.cookies['hotel_refresh'].value
        first = self.client.post(reverse('token-refresh'), {}, format='json')
        self.assertEqual(first.status_code, 200)
        rotated = first.cookies['hotel_refresh'].value
        self.client.cookies['hotel_refresh'] = old  # the second load never saw the new cookie
        second = self.client.post(reverse('token-refresh'), {}, format='json')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.cookies['hotel_refresh'].value, rotated)  # no extra token minted

    def test_rotated_token_is_refused_after_sign_out_or_the_grace_window(self):
        tokens = self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie').data
        old = self.client.cookies['hotel_refresh'].value
        self.client.post(reverse('token-refresh'), {}, format='json')
        # Signing out revokes the rotated token, so the grace copy must not revive it
        self.bearer(tokens['access'])
        self.assertEqual(self.client.post(reverse('logout'), {}, format='json').status_code, 205)
        self.client.credentials()
        self.client.cookies['hotel_refresh'] = old
        self.assertEqual(self.client.post(reverse('token-refresh'), {}, format='json').status_code, 401)

        # Outside the window an old token is simply rejected
        self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie')
        old = self.client.cookies['hotel_refresh'].value
        self.client.post(reverse('token-refresh'), {}, format='json')
        cache.clear()  # the grace entry has expired
        self.client.cookies['hotel_refresh'] = old
        self.assertEqual(self.client.post(reverse('token-refresh'), {}, format='json').status_code, 401)

    def test_page_reloads_do_not_use_up_the_login_budget(self):
        """Each page load refreshes the session; a busy desk must not be locked out of signing in."""
        self.login('ada@hotel.com', HTTP_X_AUTH_MODE='cookie')
        for _ in range(15):  # more than the 10/min login allowance
            self.assertEqual(self.client.post(reverse('token-refresh'), {}, format='json').status_code, 200)
        self.assertEqual(self.login('ada@hotel.com').status_code, 200)
