from django.db import models
from authentication.models import User

# Create your models here.
class ReceptionistProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='receptionist_profile')
    shift_start = models.TimeField()
    shift_end = models.TimeField()
    desk_number = models.CharField(max_length=10)

    def __str__(self):
        return f"Receptionist Profile for {self.user.get_user()}"
    