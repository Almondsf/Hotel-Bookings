from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from booking.models import Booking, Guest, GuestIdentification
from privacy.services import apply_retention
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class PrivacyTests(APITestCase):
    def setUp(self):
        cache.clear()
        room_type = RoomType.objects.create(name='Std', description='', base_price=Decimal('50000'), max_adults=2,
                                            max_children=0, bed_type='KING', bed_count=1, size=300)
        self.room = Room.objects.create(room_number='101', room_type=room_type, floor_number=1)
        self.guest = Guest.objects.create(first_name='Ada', last_name='Obi', email='ada@example.com',
                                          phone_number='08031234567', notes='Allergic to nuts')
        GuestIdentification.objects.create(guest=self.guest, document_type='PASSPORT', document_number='A1234567')
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')
        self.client.force_authenticate(self.manager)

    def past_stay(self, days_ago=10):
        check_out = timezone.localdate() - timedelta(days=days_ago)
        return Booking.objects.create(
            guest=self.guest, room=self.room, check_in_date=check_out - timedelta(days=1), check_out_date=check_out,
            number_of_adults=1, price_per_night=Decimal('50000'), total_price=Decimal('50000'),
            status=Booking.Status.CHECKED_OUT, confirmation_number=f'BK-P{days_ago:05d}',
        )

    def test_export_contains_profile_and_masks_id_numbers(self):
        self.past_stay()
        data = self.client.get(reverse('guest-export', args=[self.guest.pk])).data
        self.assertEqual(data['profile']['email'], 'ada@example.com')
        self.assertEqual(len(data['stays']), 1)
        self.assertEqual(data['identity_documents'][0]['number'], '•••• 4567')
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.GUEST_DATA_EXPORTED).exists())

    def test_anonymise_keeps_bookings_but_not_identity(self):
        booking = self.past_stay()
        response = self.client.post(reverse('guest-anonymise', args=[self.guest.pk]), {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.first_name, 'Anonymised')
        self.assertNotIn('ada', self.guest.email)
        self.assertEqual((self.guest.phone_number, self.guest.notes), (None, ''))
        self.assertFalse(GuestIdentification.objects.exists())
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())

    def test_cannot_anonymise_with_active_booking(self):
        future = timezone.localdate() + timedelta(days=5)
        Booking.objects.create(guest=self.guest, room=self.room, check_in_date=future,
                               check_out_date=future + timedelta(days=1), number_of_adults=1,
                               price_per_night=Decimal('1'), total_price=Decimal('1'), status='CONFIRMED',
                               confirmation_number='BK-FUTURE')
        self.assertEqual(self.client.post(reverse('guest-anonymise', args=[self.guest.pk])).status_code, 409)

    def test_only_managers(self):
        desk = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.client.force_authenticate(desk)
        self.assertEqual(self.client.get(reverse('guest-export', args=[self.guest.pk])).status_code, 403)

    @override_settings(GUEST_RETENTION_DAYS=30, GUEST_ID_RETENTION_DAYS=365)
    def test_retention(self):
        self.past_stay(days_ago=40)
        recent = Guest.objects.create(first_name='Bola', last_name='Ade', email='bola@example.com')
        Booking.objects.create(guest=recent, room=self.room, check_in_date=timezone.localdate() - timedelta(days=3),
                               check_out_date=timezone.localdate() - timedelta(days=2), number_of_adults=1,
                               price_per_night=Decimal('1'), total_price=Decimal('1'), status='CHECKED_OUT',
                               confirmation_number='BK-RECENT')
        anonymised, _ = apply_retention()
        self.assertEqual(anonymised, 1)
        recent.refresh_from_db()
        self.assertEqual(recent.first_name, 'Bola')
