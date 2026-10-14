from django.db import migrations
from django.db.models.functions import Lower


def lowercase_emails(apps, schema_editor):
    User = apps.get_model('authentication', 'User')
    for user in User.objects.exclude(email=Lower('email')):
        lowered = user.email.strip().lower()
        if User.objects.filter(email=lowered).exclude(pk=user.pk).exists():
            raise RuntimeError(
                f"Cannot lowercase {user.email!r}: {lowered!r} already exists. Merge these accounts first."
            )
        user.email = lowered
        user.save(update_fields=['email'])


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0003_alter_user_is_staff_alter_user_phone_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
    ]
