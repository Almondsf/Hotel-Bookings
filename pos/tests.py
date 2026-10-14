from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from billing.models import Folio
from booking.models import Booking
from pos.models import Order, Outlet, Product
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class PosTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.restaurant = Outlet.objects.get(code='restaurant')
        self.bar = Outlet.objects.get(code='bar')
        self.jollof = Product.objects.create(outlet=self.restaurant, name='Jollof rice & chicken', section='Mains',
                                             price=Decimal('8000'), charge_category='FOOD')
        self.chapman = Product.objects.create(outlet=self.bar, name='Chapman', section='Mocktails',
                                              price=Decimal('4000'), charge_category='BEVERAGE',
                                              track_stock=True, stock_quantity=2, low_stock_threshold=1)
        self.waiter = User.objects.create_user('waiter@hotel.com', 'W', 'T', 'x', role='restaurant')
        self.bartender = User.objects.create_user('bar@hotel.com', 'B', 'T', 'x', role='bar')
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')
        self.client.force_authenticate(self.waiter)

    def open_order(self, outlet=None, **extra):
        response = self.client.post(reverse('pos-order-list'), {'outlet': (outlet or self.restaurant).pk,
                                                                'table_label': 'T4', **extra}, format='json')
        assert response.status_code == 201, response.data
        return response.data

    def add(self, order, product, quantity=1):
        return self.client.post(reverse('pos-order-items', args=[order['id']]),
                                {'product': product.pk, 'quantity': quantity}, format='json')

    def in_house_guest(self):
        room_type = RoomType.objects.create(name='Std', description='', base_price=Decimal('50000'), max_adults=2,
                                            max_children=0, bed_type='KING', bed_count=1, size=300)
        room = Room.objects.create(room_number='305', room_type=room_type, floor_number=3)
        self.client.force_authenticate(self.manager)
        today = timezone.localdate()
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Kemi', 'last_name': 'Adeyemi', 'email': 'kemi@example.com'},
            'check_in_date': today.isoformat(), 'check_out_date': (today + timedelta(days=2)).isoformat(),
            'rooms': [{'room_type': room_type.id, 'room': room.id, 'number_of_adults': 1}],
        }, format='json')
        booking = Booking.objects.get(pk=response.data[0]['id'])
        self.client.post(reverse('reservation-check-in', args=[booking.pk]), {}, format='json')
        self.client.force_authenticate(self.waiter)
        return booking


class OrderTests(PosTestCase):
    def test_outlet_access_follows_role(self):
        outlets = [o['code'] for o in self.client.get(reverse('pos-outlet-list')).data]
        self.assertIn('restaurant', outlets)
        self.assertNotIn('bar', outlets)
        response = self.client.post(reverse('pos-order-list'), {'outlet': self.bar.pk}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_totals_include_taxes(self):
        order = self.open_order()
        data = self.add(order, self.jollof, 2).data
        self.assertEqual(data['totals'], {'net': '16000.00', 'tax': '1200.00', 'total': '17200.00'})

    def test_cannot_add_another_outlets_product(self):
        order = self.open_order()
        self.assertEqual(self.add(order, self.chapman).status_code, 400)

    def test_pay_cash_with_change_and_receipt(self):
        order = self.open_order()
        self.add(order, self.jollof, 2)
        url = reverse('pos-order-pay', args=[order['id']])
        self.assertEqual(self.client.post(url, {'method': 'CASH', 'tendered_amount': '10000'}, format='json').status_code, 400)
        response = self.client.post(url, {'method': 'CASH', 'tendered_amount': '20000'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'SETTLED')
        self.assertEqual(response.data['change_due'], '2800.00')
        folio = Folio.objects.get(pk=response.data['folio'])
        self.assertEqual((folio.status, folio.balance), ('SETTLED', Decimal('0.00')))
        self.assertEqual(folio.invoices.count(), 1)
        # Settled orders are closed for edits
        self.assertEqual(self.add(order, self.jollof).status_code, 409)

    def test_card_needs_reference(self):
        order = self.open_order()
        self.add(order, self.jollof)
        url = reverse('pos-order-pay', args=[order['id']])
        self.assertEqual(self.client.post(url, {'method': 'CARD_TERMINAL'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'method': 'CARD_TERMINAL', 'reference': 'RRN99'}, format='json').status_code, 200)

    def test_empty_order_cannot_be_settled(self):
        order = self.open_order()
        self.assertEqual(self.client.post(reverse('pos-order-pay', args=[order['id']]), {'method': 'CASH'}, format='json').status_code, 400)

    def test_remove_item_before_settlement(self):
        order = self.open_order()
        item_id = self.add(order, self.jollof).data['items'][0]['id']
        response = self.client.post(reverse('pos-order-remove-item', args=[order['id'], item_id]))
        self.assertEqual(response.data['items'], [])


class RoomChargeTests(PosTestCase):
    def test_charge_to_room_requires_matching_surname(self):
        booking = self.in_house_guest()
        order = self.open_order(table_label='Room 305')
        self.add(order, self.jollof)
        url = reverse('pos-order-charge-to-room', args=[order['id']])
        wrong = self.client.post(url, {'room_number': '305', 'guest_last_name': 'Okafor'}, format='json')
        self.assertEqual(wrong.status_code, 400)
        response = self.client.post(url, {'room_number': '305', 'guest_last_name': ' adeyemi '}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['room_number'], '305')
        charge = booking.folio.charges.get()
        self.assertEqual((charge.category, charge.total_amount), ('FOOD', Decimal('8600.00')))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.POS_ORDER_SETTLED).exists())

    def test_lookup_shows_initials_only(self):
        self.in_house_guest()
        response = self.client.get(reverse('pos-in-house'), {'room': '305'})
        self.assertEqual(response.data['guest_initials'], 'K. A.')
        self.assertEqual(self.client.get(reverse('pos-in-house'), {'room': '999'}).status_code, 404)


class StockAndVoidTests(PosTestCase):
    def test_stock_is_consumed_and_cannot_go_negative(self):
        self.client.force_authenticate(self.bartender)
        order = self.open_order(outlet=self.bar)
        self.add(order, self.chapman, 3)
        response = self.client.post(reverse('pos-order-pay', args=[order['id']]), {'method': 'CASH'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.chapman.refresh_from_db()
        self.assertEqual(self.chapman.stock_quantity, 2)  # rolled back

        order = self.open_order(outlet=self.bar)
        self.add(order, self.chapman, 2)
        self.client.post(reverse('pos-order-pay', args=[order['id']]), {'method': 'CASH'}, format='json')
        self.chapman.refresh_from_db()
        self.assertEqual(self.chapman.stock_quantity, 0)
        self.assertTrue(self.chapman.is_low_on_stock)

    def test_only_managers_void_and_reason_required(self):
        order = self.open_order()
        self.add(order, self.jollof)
        url = reverse('pos-order-void', args=[order['id']])
        self.assertEqual(self.client.post(url, {'reason': 'Guest left'}, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'reason': 'Guest left'}, format='json').data['status'], 'VOID')

    def test_menu_management_is_manager_only(self):
        payload = {'outlet': self.restaurant.pk, 'name': 'Pepper soup', 'price': '6000', 'charge_category': 'FOOD'}
        self.assertEqual(self.client.post(reverse('pos-product-list'), payload, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(reverse('pos-product-list'), payload, format='json').status_code, 201)
        bad = {**payload, 'name': 'Free room', 'charge_category': 'ROOM'}
        self.assertEqual(self.client.post(reverse('pos-product-list'), bad, format='json').status_code, 400)

    def test_sales_report(self):
        order = self.open_order()
        self.add(order, self.jollof, 3)
        self.client.post(reverse('pos-order-pay', args=[order['id']]), {'method': 'CASH'}, format='json')
        self.client.force_authenticate(self.manager)
        report = self.client.get(reverse('pos-sales-report')).data
        self.assertEqual(report['by_outlet'], [{'outlet': 'Restaurant', 'orders': 1, 'net': Decimal('24000.00')}])
        self.assertEqual(report['best_sellers'][0]['quantity'], 3)
        self.assertEqual(Order.objects.filter(status='SETTLED').count(), 1)
