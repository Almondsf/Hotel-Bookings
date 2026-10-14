"""
Demo data for development and sales demos.

Configures a small Lagos hotel (rooms, staff, rate plans, corporate accounts,
outlet menus) and then *simulates* the last two weeks of trading through the
real services: reservations, check-ins with ID, restaurant and bar orders,
payments, check-outs, housekeeping, maintenance, cancellations, no-shows and
a night audit closing each day. Every folio, report and audit entry is
therefore consistent, exactly as if staff had used the system.

The run ends on today's business day mid-afternoon: some arrivals still
expected, some departures not yet checked out, cleaning in progress.

    python manage.py seed_demo           # on a database with no bookings
    python manage.py seed_demo --reset   # wipe operational data and re-seed

Refuses to run outside DEBUG.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import RequestFactory
from django.test.utils import override_settings
from django.utils import timezone

from audit.models import AuditLog
from authentication.models import User
from billing import services as billing
from billing.models import (AccountPayment, Charge, CorporateAccount, ExchangeRate, Folio, FolioPayment, Invoice,
                            InvoiceSequence, PaymentMethod)
from booking import lifecycle
from booking.front_desk import walk_in
from booking.models import Booking, BookingGroup, BookingNight, Guest
from booking.services import create_staff_reservation
from hotel.clock import business_date
from hotel.errors import DomainError
from housekeeping import services as housekeeping
from housekeeping.models import HousekeepingTask
from maintenance import services as maintenance
from maintenance.models import MaintenanceTicket
from nightaudit import services as night_audit
from nightaudit.models import BusinessDay
from notifications.models import Notification
from payments.models import PaymentTransaction
from pos import services as pos
from pos.models import Order, OrderItem, Outlet, Product
from rates.models import RatePlan
from rooms.models import Amenity, Room, RoomAvailabilityOverride, RoomImage, RoomType

HISTORY_DAYS = 14
DEMO_PASSWORD = 'DemoPass#2026'
GUEST_EMAIL_DOMAIN = 'example.com'

STAFF = [
    ('manager@demo.hotel', 'Amaka', 'Okonkwo', User.Role.MANAGER),
    ('frontdesk@demo.hotel', 'Tunde', 'Adebayo', User.Role.RECEPTIONIST),
    ('accounts@demo.hotel', 'Fatima', 'Bello', User.Role.ACCOUNTANT),
    ('housekeeping@demo.hotel', 'Blessing', 'Udoh', User.Role.HOUSEKEEPING),
    ('maintenance@demo.hotel', 'Sunday', 'Akpan', User.Role.MAINTENANCE),
    ('restaurant@demo.hotel', 'Kelechi', 'Obi', User.Role.RESTAURANT),
    ('bar@demo.hotel', 'Yusuf', 'Lawal', User.Role.BAR),
]

# name, base price, adults, children, bed type, beds, size (sq ft), amenities
ROOM_TYPES = {
    'Standard Room': (Decimal('85000'), 2, 1, 'DOUBLE', 1, 250, ['WiFi', 'TV', 'Air Conditioning']),
    'Deluxe Suite': (Decimal('150000'), 3, 2, 'KING', 1, 400,
                     ['WiFi', 'TV', 'Air Conditioning', 'Mini Bar', 'Balcony']),
    'Family Suite': (Decimal('220000'), 4, 3, 'KING', 2, 600,
                     ['WiFi', 'TV', 'Air Conditioning', 'Mini Bar', 'Balcony']),
    'Executive Suite': (Decimal('350000'), 2, 1, 'KING', 1, 750,
                        ['WiFi', 'TV', 'Air Conditioning', 'Mini Bar', 'Balcony', 'Work Desk', 'Bathtub']),
}
ROOM_DESCRIPTIONS = {
    'Standard Room': "A bright, quiet room with a plush double bed, rain shower, smart TV and a desk by the window. "
                     "Everything you need for a restful night in the city.",
    'Deluxe Suite': "Generous space with a king-size bed, a sitting area and a private balcony. The minibar is stocked, "
                    "the bathroom has a walk-in shower, and there's room for a little one on request.",
    'Family Suite': "Two king-size beds and a separate lounge with dining table: plenty of room for the whole family "
                    "to spread out, with a balcony for evening breeze.",
    'Executive Suite': "Our finest suite: a king-size bed, freestanding bathtub, a proper work desk and a lounge for "
                       "receiving guests, with views over the pool and the city beyond.",
}
_photo = 'https://images.unsplash.com/photo-{}'.format
# Placeholder photography; replace with the hotel's own (first one is the primary image)
ROOM_PHOTOS = {
    'Standard Room': ['1631049307264-da0ec9d70304', '1611892440504-42a792e24d32', '1505693416388-ac5ce068fe85'],
    'Deluxe Suite': ['1618773928121-c32242e63f39', '1582719478250-c89cae4dc85b', '1591088398332-8a7791972843'],
    'Family Suite': ['1566665797739-1674de7a421a', '1560185007-cde436f6a4d0'],
    'Executive Suite': ['1578683010236-d716f9a3f461', '1590490360182-c33d57733427'],
}
ROOMS = (
    [(f'10{n}', 'Standard Room', 1) for n in range(1, 7)]
    + [(f'20{n}', 'Deluxe Suite', 2) for n in range(1, 6)]
    + [(f'30{n}', 'Family Suite', 3) for n in range(1, 4)]
    + [(f'40{n}', 'Executive Suite', 4) for n in range(1, 3)]
)

# first, last, phone, nationality, company, vip
GUESTS = [
    ('Chinedu', 'Eze', '08031234567', 'Nigerian', 'Shell Nigeria', False),
    ('Ngozi', 'Okafor', '08029876543', 'Nigerian', '', False),
    ('Musa', 'Ibrahim', '08061112222', 'Nigerian', 'Dangote Group', True),
    ('Funke', 'Adeyemi', '08075553333', 'Nigerian', '', False),
    ('Emeka', 'Nwosu', '08094445555', 'Nigerian', 'Access Bank', False),
    ('Aisha', 'Mohammed', '08035550101', 'Nigerian', '', False),
    ('Oluwaseun', 'Bakare', '08125550102', 'Nigerian', 'MTN Nigeria', False),
    ('Chiamaka', 'Nnadi', '08055550103', 'Nigerian', '', True),
    ('Babatunde', 'Ogunleye', '07035550104', 'Nigerian', 'Dangote Group', False),
    ('Halima', 'Abubakar', '08085550105', 'Nigerian', '', False),
    ('Ikechukwu', 'Okeke', '09015550106', 'Nigerian', 'Shell Nigeria', False),
    ('Temitope', 'Alabi', '08165550107', 'Nigerian', '', False),
    ('Yetunde', 'Fashola', '08025550108', 'Nigerian', 'Access Bank', False),
    ('Obinna', 'Chukwu', '08065550109', 'Nigerian', '', False),
    ('Zainab', 'Sani', '08135550110', 'Nigerian', '', False),
    ('Adebola', 'Oyelaran', '08095550111', 'Nigerian', 'MTN Nigeria', False),
    ('Kemi', 'Adebayo-Johnson', '08175550112', 'Nigerian', '', True),
    ('Efe', 'Omoregie', '08045550113', 'Nigerian', '', False),
    ('Uche', 'Anyanwu', '07065550114', 'Nigerian', '', False),
    ('Bisola', 'Olatunji', '08185550115', 'Nigerian', '', False),
    ('Kwame', 'Mensah', '+233245550116', 'Ghanaian', '', False),
    ('James', 'Whitfield', '+447700900117', 'British', 'Shell Nigeria', False),
    ('Sarah', 'Collins', '+12025550118', 'American', '', False),
    ('Jean-Pierre', 'Dubois', '+33612345619', 'French', '', False),
    ('Amara', 'Diallo', '+221775550120', 'Senegalese', '', False),
    ('Tobi', 'Ademola', '08115550121', 'Nigerian', '', False),
    ('Ifeoma', 'Eze-Williams', '08155550122', 'Nigerian', '', False),
    ('Segun', 'Arinze', '08035550123', 'Nigerian', '', False),
    ('Hauwa', 'Garba', '08065550124', 'Nigerian', '', False),
    ('David', 'Okoro', '08075550125', 'Nigerian', '', False),
]
GUEST_NOTES = {
    'Musa': 'Prefers a high floor, away from the lift. Allergic to groundnuts.',
    'Chiamaka': 'Returning guest: likes extra pillows and still water in the room.',
    'Kemi': 'Celebrity guest: do not disclose room number to callers.',
}

CORPORATE_ACCOUNTS = [
    ('shell', 'Shell Nigeria', 'Adaeze Nwankwo', 'travel@shell.example.com', Decimal('5000000'), 30),
    ('dangote', 'Dangote Group', 'Ibrahim Yusuf', 'admin@dangote.example.com', Decimal('8000000'), 45),
    ('access-bank', 'Access Bank', 'Folake Martins', 'hr@accessbank.example.com', Decimal('3000000'), 30),
    ('mtn', 'MTN Nigeria', 'Chuka Obi', 'events@mtn.example.com', Decimal('4000000'), 30),
]

# outlet code -> [(section, name, price, category, track stock, stock, low threshold)]
MENUS = {
    'restaurant': [
        ('Starters', 'Pepper Soup (Goat)', 6500, 'FOOD'),
        ('Starters', 'Asun', 5500, 'FOOD'),
        ('Starters', 'Spring Rolls', 4000, 'FOOD'),
        ('Mains', 'Jollof Rice & Grilled Chicken', 9500, 'FOOD'),
        ('Mains', 'Pounded Yam & Egusi', 10500, 'FOOD'),
        ('Mains', 'Amala & Ewedu with Assorted Meat', 9000, 'FOOD'),
        ('Mains', 'Ofada Rice & Ayamase', 9500, 'FOOD'),
        ('Mains', 'Grilled Croaker Fish & Plantain', 16000, 'FOOD'),
        ('Mains', 'Club Sandwich & Fries', 8000, 'FOOD'),
        ('Mains', 'Ribeye Steak', 22000, 'FOOD'),
        ('Desserts', 'Chocolate Lava Cake', 5000, 'FOOD'),
        ('Desserts', 'Fruit Platter', 4500, 'FOOD'),
        ('Breakfast', 'Full English Breakfast', 8500, 'FOOD'),
        ('Breakfast', 'Yam & Egg Sauce', 6000, 'FOOD'),
        ('Drinks', 'Chapman', 3500, 'BEVERAGE'),
        ('Drinks', 'Fresh Orange Juice', 3000, 'BEVERAGE'),
        ('Drinks', 'Bottled Water', 1000, 'BEVERAGE'),
    ],
    'bar': [
        ('Beer', 'Star Lager', 2500, 'BEVERAGE', 120, 24),
        ('Beer', 'Heineken', 3000, 'BEVERAGE', 96, 24),
        ('Beer', 'Guinness Foreign Extra', 3000, 'BEVERAGE', 18, 24),
        ('Cocktails', 'Zobo Mojito', 6000, 'BEVERAGE'),
        ('Cocktails', 'Long Island Iced Tea', 8000, 'BEVERAGE'),
        ('Cocktails', 'Pina Colada', 7000, 'BEVERAGE'),
        ('Spirits', 'Hennessy VS (shot)', 9000, 'BEVERAGE', 60, 10),
        ('Spirits', 'Jameson (shot)', 5000, 'BEVERAGE', 60, 10),
        ('Wine', 'House Red (glass)', 6500, 'BEVERAGE'),
        ('Wine', 'Moet & Chandon (bottle)', 95000, 'BEVERAGE', 6, 4),
        ('Soft drinks', 'Coke', 1500, 'BEVERAGE'),
        ('Soft drinks', 'Malt', 1500, 'BEVERAGE'),
        ('Bar snacks', 'Suya Platter', 7000, 'FOOD'),
        ('Bar snacks', 'Peppered Gizzard', 5000, 'FOOD'),
    ],
    'room-service': [
        ('Mains', 'Jollof Rice & Chicken (room service)', 11000, 'FOOD'),
        ('Mains', 'Spaghetti Bolognese', 9500, 'FOOD'),
        ('Mains', 'Chicken Shawarma', 6500, 'FOOD'),
        ('Breakfast', 'Continental Breakfast Tray', 9000, 'FOOD'),
        ('Minibar', 'Pringles', 3500, 'MINIBAR'),
        ('Minibar', 'Mixed Nuts', 3000, 'MINIBAR'),
        ('Minibar', 'Heineken (minibar)', 3500, 'MINIBAR'),
        ('Drinks', 'Bottled Water (1.5L)', 1500, 'BEVERAGE'),
    ],
    'laundry': [
        ('Wash & iron', 'Shirt', 2500, 'LAUNDRY'),
        ('Wash & iron', 'Trousers', 3000, 'LAUNDRY'),
        ('Wash & iron', 'Native attire (agbada)', 8000, 'LAUNDRY'),
        ('Dry clean', 'Suit (2-piece)', 9000, 'LAUNDRY'),
        ('Dry clean', 'Dress', 6000, 'LAUNDRY'),
        ('Express', 'Express surcharge (per item)', 1500, 'LAUNDRY'),
    ],
}

SPECIAL_REQUESTS = [
    '', '', '', '', 'Late arrival, around 10pm.', 'Airport pickup from MMIA please.', 'Non-smoking room.',
    'Extra bed for a child.', 'Honeymoon couple: flowers in the room if possible.', 'Quiet room away from the lift.',
    'Early check-in requested.', 'Vegetarian meals.',
]

MAINTENANCE_ISSUES = [
    ('AC not cooling', 'HVAC', 'HIGH', 'Guest reports the split unit blows warm air.'),
    ('Leaking shower head', 'PLUMBING', 'MEDIUM', 'Constant drip from the shower head.'),
    ('TV has no signal', 'IT', 'LOW', 'DSTV decoder shows E48-32.'),
    ('Bedside lamp not working', 'ELECTRICAL', 'LOW', ''),
    ('Wardrobe door off its hinge', 'FURNITURE', 'MEDIUM', ''),
    ('Fridge not cold', 'APPLIANCE', 'MEDIUM', 'Minibar fridge warm to the touch.'),
    ('Wi-Fi drops every few minutes', 'IT', 'MEDIUM', ''),
    ('Blocked toilet', 'PLUMBING', 'URGENT', ''),
]
PUBLIC_AREA_ISSUES = [
    ('Generator 2 overdue for service', 'Generator house', 'GENERATOR', 'HIGH',
     'Running hours past the 250h service interval.'),
    ('Lobby restroom tap leaking', 'Lobby restroom', 'PLUMBING', 'LOW', ''),
    ('Pool pump making noise', 'Pool deck', 'OTHER', 'MEDIUM', ''),
]


class Command(BaseCommand):
    help = "Create a demo hotel and simulate two weeks of trading through the real services (development only)."

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help="Delete bookings, folios, orders, tasks, tickets, business days and the audit log "
                                 "first. Users, rooms and configuration are kept.")
        parser.add_argument('--seed', type=int, default=2026, help="Random seed (same seed, same hotel).")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True; it creates accounts with a known password.")
        if not options['reset'] and (Booking.objects.exists() or BusinessDay.objects.exists()):
            raise CommandError("The database already has bookings or business days. "
                               "Run with --reset to wipe operational data and re-seed.")

        self.rng = random.Random(options['seed'])
        self.skipped = []
        # Guest notifications still get recorded, but no emails are printed or sent
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'), transaction.atomic():
            if options['reset']:
                self.reset()
            self.configure()
            self.simulate()
        self.report()

    # --- Setup ---------------------------------------------------------------

    def reset(self):
        # Children before parents (PROTECT foreign keys). Queryset deletes skip the
        # per-instance guards on Invoice and AuditLog, which is intended here only.
        for model in [Notification, PaymentTransaction, Invoice, OrderItem, Order, Charge, FolioPayment,
                      AccountPayment, Folio, InvoiceSequence, BookingNight, Booking, BookingGroup,
                      HousekeepingTask, MaintenanceTicket, RoomAvailabilityOverride, BusinessDay, AuditLog]:
            model.objects.all().delete()
        Guest.objects.filter(email__endswith=f'@{GUEST_EMAIL_DOMAIN}').delete()
        Room.objects.update(status=Room.Status.AVAILABLE, housekeeping_status=Room.Housekeeping.CLEAN)
        self.stdout.write('Operational data wiped.')

    def configure(self):
        amenities = {}
        for name in {a for spec in ROOM_TYPES.values() for a in spec[6]}:
            amenities[name], _ = Amenity.objects.get_or_create(name=name, defaults={
                'is_premium': name in ('Mini Bar', 'Balcony', 'Bathtub')})

        self.room_types = {}
        for name, (price, adults, children, bed, beds, size, amenity_names) in ROOM_TYPES.items():
            room_type, _ = RoomType.objects.update_or_create(name=name, defaults={
                'description': ROOM_DESCRIPTIONS[name],
                'base_price': price, 'max_adults': adults, 'max_children': children,
                'bed_type': bed, 'bed_count': beds, 'size': size,
            })
            room_type.amenities.set([amenities[a] for a in amenity_names])
            self.room_types[name] = room_type
        for name, photos in ROOM_PHOTOS.items():
            room_type = self.room_types[name]
            room_type.images.exclude(image_url__in=[_photo(p) for p in photos]).delete()
            for order, photo_id in enumerate(photos):
                RoomImage.objects.update_or_create(room_type=room_type, image_url=_photo(photo_id), defaults={
                    'description': name, 'is_primary': order == 0, 'order': order})
        for number, type_name, floor in ROOMS:
            Room.objects.update_or_create(room_number=number, defaults={
                'room_type': self.room_types[type_name], 'floor_number': floor})

        self.staff = {}
        self.new_staff = []
        for email, first, last, role in STAFF:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, first, last, DEMO_PASSWORD, role=role)
                self.new_staff.append(user)
            self.staff[role] = user

        self.accounts = {}
        for code, name, contact, email, limit, terms in CORPORATE_ACCOUNTS:
            self.accounts[name], _ = CorporateAccount.objects.update_or_create(code=code, defaults={
                'name': name, 'contact_name': contact, 'email': email, 'credit_limit': limit,
                'payment_terms_days': terms, 'phone': '+234 1 555 0100', 'address': 'Victoria Island, Lagos',
            })

        self.plans = {'BAR': RatePlan.objects.get(code=RatePlan.BAR_CODE)}
        for code, defaults in [
            ('BB', {'name': 'Bed & Breakfast', 'meal_plan': RatePlan.MealPlan.BED_AND_BREAKFAST,
                    'adjustment_percent': Decimal('12'), 'description': 'Includes breakfast for two.'}),
            ('NRF', {'name': 'Advance Saver (non-refundable)', 'adjustment_percent': Decimal('-15'),
                     'is_refundable': False, 'min_advance_days': 7,
                     'description': 'Pay now, save 15%. No refunds on cancellation.'}),
            ('WEEKLY', {'name': 'Long Stay', 'adjustment_percent': Decimal('-10'), 'min_stay': 5,
                        'description': '10% off stays of five nights or more.'}),
            ('DETTY', {'name': 'Detty December Promo', 'adjustment_percent': Decimal('-8'), 'promo_code': 'DETTY25',
                       'is_public': True, 'description': 'Promo code rate for the festive season.'}),
            ('CORP-DANGOTE', {'name': 'Dangote Group Negotiated', 'adjustment_percent': Decimal('-18'),
                              'is_public': False, 'corporate_account': self.accounts['Dangote Group'],
                              'meal_plan': RatePlan.MealPlan.BED_AND_BREAKFAST}),
            ('CORP-SHELL', {'name': 'Shell Nigeria Negotiated', 'adjustment_percent': Decimal('-15'),
                            'is_public': False, 'corporate_account': self.accounts['Shell Nigeria']}),
        ]:
            self.plans[code], _ = RatePlan.objects.update_or_create(code=code, defaults=defaults)

        if not ExchangeRate.objects.exists():
            for currency, rate in [('USD', '1545.00'), ('GBP', '1960.00'), ('EUR', '1675.00')]:
                ExchangeRate.objects.create(currency=currency, rate=Decimal(rate), set_by=self.staff['accountant'])

        self.products = {}
        for code, items in MENUS.items():
            outlet = Outlet.objects.get(code=code)
            self.products[code] = []
            for section, name, price, category, *stock in items:
                product, _ = Product.objects.update_or_create(outlet=outlet, name=name, defaults={
                    'section': section, 'price': Decimal(price), 'charge_category': category, 'is_available': True,
                    'track_stock': bool(stock), 'stock_quantity': stock[0] if stock else 0,
                    'low_stock_threshold': stock[1] if stock else 0,
                })
                self.products[code].append(product)
        self.outlets = {o.code: o for o in Outlet.objects.all()}

        self.guests = []
        for first, last, phone, nationality, company, vip in GUESTS:
            email = f"{first}.{last}".lower().replace(' ', '') + f'@{GUEST_EMAIL_DOMAIN}'
            guest, _ = Guest.objects.update_or_create(email=email, defaults={
                'first_name': first, 'last_name': last, 'phone_number': phone, 'nationality': nationality,
                'country': 'Nigeria' if nationality == 'Nigerian' else nationality, 'company_name': company,
                'is_vip': vip, 'notes': GUEST_NOTES.get(first, ''), 'accepts_marketing': self.rng.random() < 0.4,
                'address': self.rng.choice(['Lekki Phase 1, Lagos', 'Ikoyi, Lagos', 'Wuse II, Abuja', 'GRA, Port Harcourt',
                                            'Bodija, Ibadan', 'Independence Layout, Enugu', '']),
            })
            self.guests.append(guest)

        self.stdout.write(f'Hotel configured: {len(ROOMS)} rooms, {len(self.staff)} staff, '
                          f'{len(self.guests)} guests, {Product.objects.count()} menu items.')

    # --- Simulation ----------------------------------------------------------

    def request(self, role):
        request = RequestFactory().post('/', REMOTE_ADDR='127.0.0.1', HTTP_USER_AGENT='seed_demo')
        request.user = self.staff[role]
        return request

    def attempt(self, label, operation, *args, **kwargs):
        """Run one front-desk action; a refusal by the business rules is noted, not fatal."""
        try:
            with transaction.atomic():
                return operation(*args, **kwargs)
        except DomainError as e:
            self.skipped.append(f'{label}: {e}')
            return None

    def simulate(self):
        today = timezone.localdate()
        start = today - timedelta(days=HISTORY_DAYS)
        BusinessDay.objects.create(date=start, status=BusinessDay.Status.OPEN)

        while True:
            day = business_date()
            is_today = day == today
            self.take_reservations(day, count=6 if day == start else self.rng.randint(2, 4))
            if self.rng.random() < 0.3:
                self.cancel_one(day)
            self.check_out_departures(day, leave_some=is_today)
            self.housekeeping(day, finish_all=not is_today)
            self.check_in_arrivals(day, leave_some=is_today)
            self.walk_ins(day)
            self.outlet_sales(day)
            self.maintenance(day, is_today)
            if day.weekday() == 4:
                self.city_ledger_payments()
            if is_today:
                break
            night_audit.run(request=self.request(User.Role.MANAGER), auto_no_show=True)

        self.future_bookings(today)

    def stay_party(self, room_type):
        adults = self.rng.randint(1, room_type.max_adults)
        children = self.rng.randint(0, room_type.max_children) if adults > 1 and self.rng.random() < 0.3 else 0
        return {'room_type': room_type, 'number_of_adults': adults, 'number_of_children': children}

    def pick_room_type(self):
        return self.rng.choices(list(self.room_types.values()), weights=[3, 4, 2, 1])[0]

    def free_guest(self, check_in, check_out):
        """A guest with no other stay over these dates (nobody is in two rooms at once)."""
        busy = set(Booking.objects.blocking().overlapping(check_in, check_out).values_list('guest_id', flat=True))
        return self.rng.choice([g for g in self.guests if g.pk not in busy] or self.guests)

    def reserve(self, day, *, check_in, nights, rooms=1):
        guest = self.free_guest(check_in, check_in + timedelta(days=nights))
        account = self.accounts.get(guest.company_name)
        plan = None
        source = self.rng.choice([Booking.Source.PHONE, Booking.Source.EMAIL, Booking.Source.FRONT_DESK,
                                  Booking.Source.OTA, Booking.Source.TRAVEL_AGENT])
        if account:
            source = Booking.Source.CORPORATE
            plan = self.plans.get('CORP-DANGOTE' if account.code == 'dangote' else
                                  'CORP-SHELL' if account.code == 'shell' else 'BAR')
        elif nights >= 5:
            plan = self.plans['WEEKLY']
        elif (check_in - day).days >= 7 and self.rng.random() < 0.4:
            plan = self.plans['NRF']
        elif self.rng.random() < 0.35:
            plan = self.plans['BB']
        room_type = self.pick_room_type()
        return self.attempt(
            f'Reservation for {guest}', create_staff_reservation,
            guest=guest, rooms=[self.stay_party(room_type) for _ in range(rooms)], check_in_date=check_in,
            check_out_date=check_in + timedelta(days=nights), source=source,
            special_requests=self.rng.choice(SPECIAL_REQUESTS), rate_plan=plan,
            corporate_account=account if source == Booking.Source.CORPORATE else None,
            notes='Wedding party' if rooms > 2 else 'Family trip' if rooms > 1 else '',
            request=self.request(User.Role.RECEPTIONIST),
        )

    def take_reservations(self, day, count):
        for _ in range(count):
            lead = self.rng.choice([0, 0, 1, 1, 2, 3, 4, 5, 7, 10, 14])
            nights = self.rng.choice([1, 1, 2, 2, 2, 3, 3, 4, 5, 6])
            self.reserve(day, check_in=day + timedelta(days=lead), nights=nights)
        if self.rng.random() < 0.15:
            self.reserve(day, check_in=day + timedelta(days=self.rng.randint(3, 10)), nights=2,
                         rooms=self.rng.randint(2, 3))

    def future_bookings(self, today):
        """Fill the forward calendar so the reservation and availability views have something to show."""
        for _ in range(14):
            self.reserve(today, check_in=today + timedelta(days=self.rng.randint(1, 30)),
                         nights=self.rng.choice([1, 2, 2, 3, 4, 5]))
        self.reserve(today, check_in=today + timedelta(days=21), nights=3, rooms=4)

    def cancel_one(self, day):
        candidates = list(Booking.objects.filter(status=Booking.Status.CONFIRMED, check_in_date__gt=day))
        if not candidates:
            return
        booking = self.rng.choice(candidates)
        waive = self.rng.random() < 0.5
        self.attempt(f'Cancel {booking.confirmation_number}', lifecycle.cancel, booking,
                     reason=self.rng.choice(['Change of travel plans', 'Meeting postponed', 'Flight cancelled',
                                             'Booked elsewhere']),
                     waive_penalty=waive, request=self.request(User.Role.MANAGER if waive else User.Role.RECEPTIONIST))

    def identification(self, guest):
        foreign = guest.nationality != 'Nigerian'
        number = ''.join(self.rng.choice('0123456789') for _ in range(11))
        return {
            'document_type': 'PASSPORT' if foreign else self.rng.choice(['NATIONAL_ID', 'DRIVERS_LICENCE', 'PASSPORT']),
            'document_number': ('A' + number[:8]) if foreign else number,
            'issuing_country': guest.country or 'Nigeria',
            'expiry_date': business_date() + timedelta(days=self.rng.randint(200, 2000)),
        }

    def check_in_arrivals(self, day, leave_some):
        desk = self.request(User.Role.RECEPTIONIST)
        arrivals = list(Booking.objects.filter(status=Booking.Status.CONFIRMED, check_in_date=day)
                        .select_related('guest'))
        self.rng.shuffle(arrivals)
        for i, booking in enumerate(arrivals):
            if leave_some and i % 2 == 0:
                continue  # still expected this evening
            if not leave_some and self.rng.random() < 0.06:
                continue  # never turns up: night audit marks a no-show
            identification = None if booking.guest.has_valid_identification else self.identification(booking.guest)
            if not self.attempt(f'Check in {booking.confirmation_number}', lifecycle.check_in, booking,
                                identification=identification, request=desk):
                continue
            if booking.corporate_account_id is None and self.rng.random() < 0.6:
                # A deposit against the stay
                folio = billing.folio_for(booking)
                method = self.rng.choice([PaymentMethod.CARD_TERMINAL, PaymentMethod.BANK_TRANSFER,
                                          PaymentMethod.CASH])
                if booking.guest.nationality in ('American', 'British') and method == PaymentMethod.CASH:
                    self.attempt('USD deposit', billing.record_payment, folio, method=method, currency='USD',
                                 tendered_amount=Decimal(self.rng.choice([100, 200, 300])), request=desk)
                else:
                    self.attempt('Deposit', billing.record_payment, folio, method=method,
                                 amount=booking.total_price, reference=self.reference(method), request=desk)

    def walk_ins(self, day):
        if self.rng.random() > 0.35:
            return
        nights = self.rng.randint(1, 3)
        guest = self.free_guest(day, day + timedelta(days=nights))
        room_type = self.pick_room_type()
        free =Room.objects.filter(room_type=room_type, status=Room.Status.AVAILABLE,
                                   housekeeping_status=Room.Housekeeping.CLEAN)
        if not free.exists():
            return
        booking = self.attempt(
            f'Walk-in {guest}', walk_in, guest=guest, room=self.stay_party(room_type),
            check_out_date=day + timedelta(days=nights),
            identification=None if guest.has_valid_identification else self.identification(guest),
            request=self.request(User.Role.RECEPTIONIST),
        )
        if booking:
            self.attempt('Walk-in payment', billing.record_payment, billing.folio_for(booking),
                         method=PaymentMethod.CASH, amount=booking.total_price,
                         request=self.request(User.Role.RECEPTIONIST))

    def reference(self, method):
        if method == PaymentMethod.CASH:
            return ''
        prefix = {'CARD_TERMINAL': 'POS', 'BANK_TRANSFER': 'TRF'}.get(method, 'REF')
        return f"{prefix}-{self.rng.randint(10**7, 10**8 - 1)}"

    def check_out_departures(self, day, leave_some):
        desk = self.request(User.Role.RECEPTIONIST)
        departures = list(Booking.objects.filter(status=Booking.Status.CHECKED_IN, check_out_date__lte=day)
                          .select_related('corporate_account'))
        for i, booking in enumerate(departures):
            if leave_some and i % 2 == 1:
                continue  # still to come down to the desk
            folio = lifecycle.bring_folio_up_to_date(booking, request=desk)
            balance = folio.balance
            if booking.corporate_account_id and balance > 0:
                self.attempt(f'Check out {booking.confirmation_number}', lifecycle.check_out, booking,
                             transfer_to_account=booking.corporate_account, request=desk)
                continue
            if balance > 0:
                method = self.rng.choice([PaymentMethod.CARD_TERMINAL, PaymentMethod.CARD_TERMINAL,
                                          PaymentMethod.BANK_TRANSFER, PaymentMethod.CASH])
                self.attempt('Settlement', billing.record_payment, folio, method=method, amount=balance,
                             reference=self.reference(method), request=desk)
            elif balance < 0:
                self.attempt('Refund', billing.refund, folio, amount=-balance, method=PaymentMethod.CASH,
                             reason='Unused deposit', request=desk)
            self.attempt(f'Check out {booking.confirmation_number}', lifecycle.check_out, booking, request=desk)

    def housekeeping(self, day, finish_all):
        housekeeping.generate_daily_tasks(day)
        staff = self.request(User.Role.HOUSEKEEPING)
        tasks = list(HousekeepingTask.objects.filter(date=day, status=HousekeepingTask.Status.PENDING)
                     .select_related('room'))
        if finish_all:
            for task in tasks:
                if task.task_type == HousekeepingTask.TaskType.STAYOVER and self.rng.random() < 0.08:
                    self.attempt('Skip task', housekeeping.skip_task, task, request=staff,
                                 reason='Do Not Disturb sign on the door')
                else:
                    self.attempt('Clean room', housekeeping.complete_task, task, request=staff)
            return
        # Today: rush rooms done first, a couple in progress, the rest still to do
        tasks = [t for t in tasks if not (t.task_type == HousekeepingTask.TaskType.DEPARTURE_CLEAN
                                          and t.room.status == Room.Status.OCCUPIED)]  # guest not out yet
        tasks.sort(key=lambda t: not t.is_rush)
        for i, task in enumerate(tasks):
            if task.is_rush or i < 2:
                self.attempt('Clean room', housekeeping.complete_task, task, request=staff)
            elif i < 4:
                self.attempt('Start task', housekeeping.start_task, task, request=staff)

    def outlet_sales(self, day):
        in_house = list(Booking.objects.filter(status=Booking.Status.CHECKED_IN).select_related('guest', 'room'))
        # Room charges from in-house guests
        for booking in in_house:
            for outlet_code, chance in [('restaurant', 0.55), ('bar', 0.35), ('room-service', 0.3), ('laundry', 0.15)]:
                if self.rng.random() < chance:
                    order = self.order(outlet_code, table=f'Room {booking.room.room_number}')
                    self.attempt('Charge to room', pos.charge_to_room, order, room_number=booking.room.room_number,
                                 guest_last_name=booking.guest.last_name, request=self.request(User.Role.MANAGER))
        # Paying customers off the street
        for outlet_code in ['restaurant', 'restaurant', 'bar', 'bar', 'bar']:
            if self.rng.random() < 0.6:
                order = self.order(outlet_code, table=f'Table {self.rng.randint(1, 20)}',
                                   covers=self.rng.randint(1, 4))
                method = self.rng.choice([PaymentMethod.CASH, PaymentMethod.CARD_TERMINAL,
                                          PaymentMethod.BANK_TRANSFER])
                self.attempt('Pay now', pos.pay_now, order, method=method, reference=self.reference(method),
                             request=self.request(User.Role.MANAGER))
        if day == timezone.localdate():
            # A couple of tables still eating
            for table in ['Table 4', 'Table 11']:
                self.order('restaurant', table=table, covers=2)
            self.order('bar', table='Bar seat 3')

    def order(self, outlet_code, *, table, covers=1):
        user = self.staff[User.Role.MANAGER]
        order = pos.open_order(self.outlets[outlet_code], user=user, table_label=table, covers=covers)
        for product in self.rng.sample(self.products[outlet_code], k=self.rng.randint(1, 3)):
            pos.add_item(order, product, quantity=self.rng.choice([1, 1, 1, 2]), user=user)
        return order

    def maintenance(self, day, is_today):
        engineer = self.request(User.Role.MAINTENANCE)
        if self.rng.random() < 0.45:
            title, category, priority, description = self.rng.choice(MAINTENANCE_ISSUES)
            room = self.rng.choice(list(Room.objects.all()))
            ticket, _ = maintenance.report(request=self.request(User.Role.HOUSEKEEPING), room=room, title=title,
                                           description=description, category=category, priority=priority)
            if not is_today:
                if self.rng.random() < 0.75:
                    self.attempt('Resolve ticket', maintenance.resolve, ticket, request=engineer,
                                 notes=self.rng.choice(['Replaced faulty part.', 'Cleaned and re-gassed the unit.',
                                                        'Tightened fittings, tested OK.', 'Reset and reconfigured.']))
                elif self.rng.random() < 0.5:
                    maintenance.update_status(ticket, MaintenanceTicket.Status.ON_HOLD, request=engineer)
            elif self.rng.random() < 0.5:
                maintenance.update_status(ticket, MaintenanceTicket.Status.IN_PROGRESS, request=engineer)
        if is_today:
            for title, location, category, priority, description in PUBLIC_AREA_ISSUES:
                maintenance.report(request=self.request(User.Role.MANAGER), location=location, title=title,
                                   description=description, category=category, priority=priority)
            # A room off sale for repairs: pick one nobody needs for the next few days
            until = day + timedelta(days=3)
            for room in Room.objects.filter(status=Room.Status.AVAILABLE).order_by('-room_number'):
                if not maintenance.affected_bookings(room, day, until):
                    maintenance.report(request=self.request(User.Role.MANAGER), room=room,
                                       title='Water damage to ceiling', category='PLUMBING', priority='URGENT',
                                       description='Leak from the floor above; ceiling board to be replaced.',
                                       out_of_order_until=until)
                    break

    def city_ledger_payments(self):
        for account in CorporateAccount.objects.all():
            owed = account.balance
            if owed > 0 and self.rng.random() < 0.6:
                self.attempt('Account payment', billing.record_account_payment, account,
                             amount=(owed * Decimal('0.7')).quantize(Decimal('1')),
                             method=PaymentMethod.BANK_TRANSFER, reference=self.reference(PaymentMethod.BANK_TRANSFER),
                             request=self.request(User.Role.ACCOUNTANT))

    # --- Summary -------------------------------------------------------------

    def report(self):
        status_counts = {label: Booking.objects.filter(status=value).count() for value, label in Booking.Status.choices}
        self.stdout.write('\nBookings: ' + ', '.join(f'{n} {label.lower()}' for label, n in status_counts.items() if n))
        self.stdout.write(f'Folios: {Folio.objects.count()}  Invoices: {Invoice.objects.count()}  '
                          f'POS orders: {Order.objects.count()}  Housekeeping tasks: {HousekeepingTask.objects.count()}  '
                          f'Maintenance tickets: {MaintenanceTicket.objects.count()}  '
                          f'Closed business days: {BusinessDay.objects.filter(status=BusinessDay.Status.CLOSED).count()}')
        if self.skipped:
            self.stdout.write(f'{len(self.skipped)} actions refused by business rules (expected when the hotel is full):')
            for line in self.skipped[:8]:
                self.stdout.write(f'  - {line}')
        if self.new_staff:
            self.stdout.write(f'\nStaff accounts (password for all: {DEMO_PASSWORD}):')
            for user in self.new_staff:
                self.stdout.write(f'  {user.get_role_display():<17} {user.email}')
        self.stdout.write(self.style.SUCCESS('\nDemo data created.'))
