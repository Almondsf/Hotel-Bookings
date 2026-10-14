from django.db import migrations


def seed(apps, schema_editor):
    RatePlan = apps.get_model('rates', 'RatePlan')
    RatePlan.objects.get_or_create(code='BAR', defaults={
        'name': 'Best Available Rate', 'description': 'Our standard flexible rate.', 'is_public': True,
    })


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
