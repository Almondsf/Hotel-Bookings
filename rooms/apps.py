from django.apps import AppConfig


class RoomsConfig(AppConfig):
    name = 'rooms'

    def ready(self):
        from django.db.models.signals import m2m_changed, post_delete, post_save

        from hotel.public_cache import invalidate

        from .models import Amenity, Room, RoomImage, RoomPricing, RoomType

        # Anything shown on the public room pages: clear the cached copies when it changes
        for model in (RoomType, Room, RoomImage, Amenity, RoomPricing):
            post_save.connect(invalidate, sender=model, dispatch_uid=f'public-cache.save.{model.__name__}')
            post_delete.connect(invalidate, sender=model, dispatch_uid=f'public-cache.delete.{model.__name__}')
        m2m_changed.connect(invalidate, sender=RoomType.amenities.through, dispatch_uid='public-cache.amenities')
