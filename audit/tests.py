from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from audit.models import AuditLog
from audit.services import client_ip, record
from authentication.models import User


class AuditLogTests(TestCase):
    def test_entries_are_immutable(self):
        entry = record(AuditLog.Action.LOGOUT, actor_email='a@hotel.com')
        entry.action = AuditLog.Action.LOGIN_SUCCEEDED
        with self.assertRaises(RuntimeError):
            entry.save()
        with self.assertRaises(RuntimeError):
            entry.delete()

    def test_forwarded_for_ignored_without_trusted_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='1.2.3.4', HTTP_X_FORWARDED_FOR='6.6.6.6')
        self.assertEqual(client_ip(request), '1.2.3.4')

    def test_forwarded_for_used_behind_trusted_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 5.5.5.5')
        with self.settings(REST_FRAMEWORK={'NUM_PROXIES': 1}):
            # Only the address our own proxy appended is trusted
            self.assertEqual(client_ip(request), '5.5.5.5')


class AuditLogApiTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user('m@hotel.com', 'M', 'Gr', 'x', role=User.Role.MANAGER)
        self.receptionist = User.objects.create_user('r@hotel.com', 'R', 'Ec', 'x', role=User.Role.RECEPTIONIST)
        record(AuditLog.Action.LOGOUT, actor=self.receptionist)
        record(AuditLog.Action.LOGOUT, actor=self.manager)

    def test_requires_audit_capability(self):
        self.client.force_authenticate(self.receptionist)
        self.assertEqual(self.client.get(reverse('audit-log-list')).status_code, 403)

    def test_list_and_filter(self):
        self.client.force_authenticate(self.manager)
        response = self.client.get(reverse('audit-log-list'), {'actor': self.receptionist.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(self.client.get(reverse('audit-log-list'), {'actor': 'abc'}).data['count'], 0)
