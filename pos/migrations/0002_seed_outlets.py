from django.db import migrations

OUTLETS = [
    ('restaurant', 'Restaurant', 'RESTAURANT', ['restaurant']),
    ('bar', 'Pool Bar', 'BAR', ['bar']),
    ('room-service', 'Room Service', 'ROOM_SERVICE', ['restaurant', 'receptionist']),
    ('laundry', 'Laundry', 'LAUNDRY', ['laundry', 'housekeeping']),
]


def seed(apps, schema_editor):
    Outlet = apps.get_model('pos', 'Outlet')
    for code, name, kind, roles in OUTLETS:
        Outlet.objects.get_or_create(code=code, defaults={'name': name, 'kind': kind, 'allowed_roles': roles})


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
