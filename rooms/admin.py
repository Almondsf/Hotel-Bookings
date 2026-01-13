from django.contrib import admin
from .models import Amenity, RoomType, Room, RoomPricing, RoomAvailabilityOverride, RoomImage
# Register your models here.
admin.site.register(Amenity)
admin.site.register(RoomType)
admin.site.register(Room)
admin.site.register(RoomPricing)
admin.site.register(RoomAvailabilityOverride)
admin.site.register(RoomImage)
