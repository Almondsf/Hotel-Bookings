from django.contrib import admin
from .models import Booking, Payment, Guest

# Register your models here.
admin.site.register(Booking)
admin.site.register(Payment)
admin.site.register(Guest)