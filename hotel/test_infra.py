import os
import unittest
from decimal import Decimal

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from hotel import public_cache
from hotel.checks import shared_cache_check
from hotel.infra import cache_config, database_config, is_shared_cache
from rooms.models import Room, RoomType


class DatabaseConfigTests(SimpleTestCase):
    URL = 'postgres://hotel:secret@db:5432/hotel'

    def test_postgres_connections_are_pooled(self):
        config = database_config(self.URL, pool_min=2, pool_max=8)
        self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config['OPTIONS']['pool'], {'min_size': 2, 'max_size': 8, 'timeout': 10})
        self.assertEqual(config['CONN_MAX_AGE'], 0)  # Django refuses persistent connections alongside a pool

    def test_without_the_pool_connections_are_kept_and_health_checked(self):
        config = database_config(self.URL, pool=False, conn_max_age=90)
        self.assertNotIn('pool', config.get('OPTIONS', {}))
        self.assertEqual((config['CONN_MAX_AGE'], config['CONN_HEALTH_CHECKS']), (90, True))

    def test_sqlite_is_left_alone(self):
        config = database_config('sqlite:///db.sqlite3')
        self.assertNotIn('pool', config.get('OPTIONS', {}))
        self.assertNotIn('CONN_HEALTH_CHECKS', config)


class CacheConfigTests(SimpleTestCase):
    def test_redis_uses_djangos_own_backend(self):
        for url in ('redis://redis:6379/0', 'rediss://user:pass@cache.example.com:6380/1'):
            config = cache_config(url)
            self.assertEqual(config['BACKEND'], 'django.core.cache.backends.redis.RedisCache')
            self.assertEqual(config['LOCATION'], url)
            self.assertTrue(is_shared_cache(config))

    def test_in_memory_cache_is_not_shared(self):
        self.assertFalse(is_shared_cache(cache_config('locmemcache://')))
        self.assertTrue(is_shared_cache(cache_config('dbcache://django_cache')))

    def test_deploy_check_warns_about_a_per_process_cache(self):
        with override_settings(CACHES={'default': cache_config('locmemcache://')}):
            self.assertEqual([w.id for w in shared_cache_check(None)], ['hotel.W001'])
        with override_settings(CACHES={'default': cache_config('redis://redis:6379/0')}):
            self.assertEqual(shared_cache_check(None), [])


@unittest.skipUnless(os.environ.get('REDIS_URL'), 'set REDIS_URL to test against a real Redis (CI does)')
class RedisCacheTests(SimpleTestCase):
    """The shared cache really works over Redis: counters (rate limits) and stored values."""

    def test_redis_round_trip(self):
        from django.core.cache.backends.redis import RedisCache

        config = cache_config(os.environ['REDIS_URL'])
        cache = RedisCache(config['LOCATION'], {'KEY_PREFIX': 'test-infra'})
        cache.set('greeting', {'hello': 'world'}, timeout=30)
        self.assertEqual(cache.get('greeting'), {'hello': 'world'})
        cache.set('hits', 1, timeout=30)
        self.assertEqual(cache.incr('hits'), 2)
        cache.delete_many(['greeting', 'hits'])


@override_settings(PUBLIC_CACHE_SECONDS=300)
class PublicCacheTests(TestCase):
    def setUp(self):
        public_cache.invalidate()
        self.suite = RoomType.objects.create(name='Garden Suite', description='x', base_price=Decimal('90000'),
                                             max_adults=2, max_children=1, bed_type='KING', bed_count=1, size=400)
        self.room = Room.objects.create(room_number='501', room_type=self.suite, floor_number=5)

    def get(self, name, *args):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse(name, args=args))
        self.assertEqual(response.status_code, 200)
        return response.json(), len(ctx)

    def test_room_types_are_served_from_the_cache_until_something_changes(self):
        first, queries = self.get('room-type-list')
        self.assertGreater(queries, 0)
        again, queries = self.get('room-type-list')
        self.assertEqual((again, queries), (first, 0))

        self.suite.name = 'Garden Suite Deluxe'
        self.suite.save()
        names = [rt['name'] for rt in self.get('room-type-list')[0]]
        self.assertEqual(names, ['Garden Suite Deluxe'])

    def test_a_room_going_out_of_order_shows_at_once(self):
        self.assertEqual(self.get('room-type-detail', self.suite.slug)[0]['available_room_count'], 1)
        self.room.status = Room.Status.OUT_OF_SERVICE
        self.room.save()
        self.assertEqual(self.get('room-type-detail', self.suite.slug)[0]['available_room_count'], 0)

    def test_a_missing_room_type_is_not_cached(self):
        self.assertEqual(self.client.get(reverse('room-type-detail', args=['nope'])).status_code, 404)
        RoomType.objects.create(name='Nope', slug='nope', description='x', base_price=Decimal('1'),
                                max_adults=1, max_children=0, bed_type='KING', bed_count=1, size=10)
        self.assertEqual(self.client.get(reverse('room-type-detail', args=['nope'])).status_code, 200)

    @override_settings(PUBLIC_CACHE_SECONDS=0)
    def test_turned_off_it_always_reads_the_database(self):
        self.get('room-type-list')
        self.assertGreater(self.get('room-type-list')[1], 0)
