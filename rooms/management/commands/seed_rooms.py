from django.core.management.base import BaseCommand
from rooms.models import RoomType, Room, Amenity, RoomImage

class Command(BaseCommand):
    help = 'Seeds the database with test room data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding database...')

        # Create Amenities
        wifi, _ = Amenity.objects.get_or_create(
            name="WiFi",
            defaults={"description": "High-speed internet", "is_premium": False}
        )
        tv, _ = Amenity.objects.get_or_create(
            name="TV",
            defaults={"description": "Flat screen TV", "is_premium": False}
        )
        minibar, _ = Amenity.objects.get_or_create(
            name="Mini Bar",
            defaults={"description": "Stocked mini bar", "is_premium": True}
        )
        ac, _ = Amenity.objects.get_or_create(
            name="Air Conditioning",
            defaults={"description": "Climate control", "is_premium": False}
        )
        balcony, _ = Amenity.objects.get_or_create(
            name="Balcony",
            defaults={"description": "Private balcony", "is_premium": True}
        )

        self.stdout.write('✓ Amenities created')

        # Create Room Types
        standard, _ = RoomType.objects.get_or_create(
            name="Standard Room",
            defaults={
                "description": "Comfortable room with essential amenities",
                "base_price": 100.00,
                "max_adults": 2,
                "max_children": 1,
                "bed_type": "DOUBLE",
                "bed_count": 1,
                "size": 250
            }
        )
        standard.amenities.set([wifi, tv, ac])

        deluxe, _ = RoomType.objects.get_or_create(
            name="Deluxe Suite",
            defaults={
                "description": "Spacious suite with premium amenities",
                "base_price": 200.00,
                "max_adults": 3,
                "max_children": 2,
                "bed_type": "KING",
                "bed_count": 1,
                "size": 400
            }
        )
        deluxe.amenities.set([wifi, tv, ac, minibar, balcony])

        family, _ = RoomType.objects.get_or_create(
            name="Family Suite",
            defaults={
                "description": "Large suite perfect for families",
                "base_price": 300.00,
                "max_adults": 4,
                "max_children": 3,
                "bed_type": "KING",
                "bed_count": 2,
                "size": 600
            }
        )
        family.amenities.set([wifi, tv, ac, minibar, balcony])

        self.stdout.write('✓ Room types created')

        # Create Rooms
        rooms_data = [
            ("101", standard, 1),
            ("102", standard, 1),
            ("103", standard, 1),
            ("201", deluxe, 2),
            ("202", deluxe, 2),
            ("301", family, 3),
            ("302", family, 3),
        ]

        for room_number, room_type, floor in rooms_data:
            Room.objects.get_or_create(
                room_number=room_number,
                defaults={
                    "room_type": room_type,
                    "floor_number": floor,
                    "status": "AVAILABLE"
                }
            )

        self.stdout.write('✓ Rooms created')

        # Create Images
        images_data = [
            (standard, "https://images.unsplash.com/photo-1611892440504-42a792e24d32", "Standard Room"),
            (deluxe, "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b", "Deluxe Suite"),
            (family, "https://images.unsplash.com/photo-1566665797739-1674de7a421a", "Family Suite"),
        ]

        for room_type, url, desc in images_data:
            RoomImage.objects.get_or_create(
                room_type=room_type,
                image_url=url,
                defaults={
                    "description": desc,
                    "is_primary": True,
                    "order": 1
                }
            )

        self.stdout.write('✓ Images created')
        self.stdout.write(self.style.SUCCESS('Database seeded successfully!'))