from decimal import Decimal

from django.db import migrations

ALL_SALES = ['ROOM', 'FOOD', 'BEVERAGE', 'MINIBAR', 'LAUNDRY', 'SPA', 'TRANSPORT', 'TELEPHONE', 'MISC', 'ALLOWANCE']
HOSPITALITY = ['ROOM', 'FOOD', 'BEVERAGE', 'MINIBAR', 'ALLOWANCE']

# Common Nigerian hotel levies. Only VAT is switched on by default; enable
# the others in the admin if the hotel charges them.
RULES = [
    ('vat', 'VAT', Decimal('0.0750'), ALL_SALES, True, 10),
    ('service-charge', 'Service Charge', Decimal('0.1000'), HOSPITALITY, False, 20),
    ('consumption-tax', 'Consumption Tax (Lagos State)', Decimal('0.0500'), HOSPITALITY, False, 30),
]


def seed(apps, schema_editor):
    TaxRule = apps.get_model('billing', 'TaxRule')
    for code, name, rate, categories, active, order in RULES:
        TaxRule.objects.get_or_create(code=code, defaults={
            'name': name, 'rate': rate, 'categories': categories, 'is_active': active, 'sort_order': order,
        })


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
