"""
Load test for the public website's API: simulated guests browsing and searching.

    python deploy/loadtest.py --base-url https://staging.example.com --users 50 --duration 120

Each simulated guest repeats what a real visitor does: load the hotel's details and
room types, open a room, then search availability for random dates and party sizes
(now and then a large group, which also builds group plans). It reports throughput
and response times per endpoint and exits non-zero when the 95th percentile or the
error rate misses its target, so it can gate a deploy.

Standard library only. Point it at a staging copy, not the live hotel. Rate limits are
per address (nginx: 30 requests a second; the app: THROTTLE_ANON, 120 a minute), so a test
from one machine is soon turned away: on staging raise both for the test, or run it from
several machines. Responses turned away with 429 are counted separately, not as errors.
"""
import argparse
import http.client
import json
import random
import sys
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode, urlsplit


class Client:
    """One keep-alive connection per simulated guest, like a browser tab."""

    def __init__(self, base_url, timeout):
        parts = urlsplit(base_url)
        self.prefix = parts.path.rstrip('/')
        connection = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        self.connect = lambda: connection(parts.netloc, timeout=timeout)
        self.conn = self.connect()

    def get(self, path, params=None):
        url = self.prefix + path + (f'?{urlencode(params)}' if params else '')
        for attempt in (1, 2):  # a keep-alive connection the server closed is reopened once
            try:
                self.conn.request('GET', url, headers={'Accept': 'application/json'})
                response = self.conn.getresponse()
                return response.status, response.read()
            except (http.client.HTTPException, ConnectionError):
                self.conn.close()
                self.conn = self.connect()
                if attempt == 2:
                    raise


class Results:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies = defaultdict(list)   # endpoint -> [seconds]
        self.errors = defaultdict(int)       # endpoint -> unexpected statuses or exceptions
        self.limited = defaultdict(int)      # endpoint -> 429s

    def add(self, name, seconds, status=None, ok=True):
        with self.lock:
            if status == 429:
                self.limited[name] += 1
            elif ok:
                self.latencies[name].append(seconds)
            else:
                self.errors[name] += 1


def timed(results, name, call, expected=(200,)):
    start = time.perf_counter()
    try:
        status, body = call()
    except Exception:
        results.add(name, time.perf_counter() - start, ok=False)
        return None
    results.add(name, time.perf_counter() - start, status, ok=status in expected)
    return json.loads(body) if status == 200 else None


def guest(base_url, timeout, results, stop, seed):
    rng = random.Random(seed)
    client = Client(base_url, timeout)
    while not stop.is_set():
        timed(results, 'hotel info', lambda: client.get('/api/hotel/'))
        room_types = timed(results, 'room types', lambda: client.get('/api/rooms/types/')) or []
        if room_types:
            slug = rng.choice(room_types)['slug']
            timed(results, 'room page', lambda: client.get(f'/api/rooms/{slug}/'))
        for _ in range(rng.randint(1, 3)):  # people try a few dates
            check_in = date.today() + timedelta(days=rng.randint(3, 60))
            big = rng.random() < 0.1
            params = {'check_in': check_in, 'check_out': check_in + timedelta(days=rng.randint(1, 4)),
                      'adults': rng.randint(8, 12) if big else rng.randint(1, 3),
                      'children': rng.randint(0, 4) if big else rng.randint(0, 2)}
            timed(results, 'search (group)' if big else 'search', lambda: client.get('/api/rooms/search/', params))
        stop.wait(rng.uniform(0.5, 2.0))  # reading the page


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))] if ordered else 0.0


def report(results, elapsed, p95_target_ms, max_error_rate):
    names = sorted(set(results.latencies) | set(results.errors) | set(results.limited))
    print(f"\n{'endpoint':18} {'requests':>9} {'req/s':>7} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'max ms':>8} "
          f"{'errors':>7} {'429s':>6}")
    total = errors = 0
    worst_p95 = 0.0
    for name in names:
        values = results.latencies[name]
        count = len(values) + results.errors[name] + results.limited[name]
        p95 = percentile(values, 95) * 1000
        worst_p95 = max(worst_p95, p95)
        total += count
        errors += results.errors[name]
        print(f"{name:18} {count:9d} {count / elapsed:7.1f} {percentile(values, 50) * 1000:8.0f} {p95:8.0f} "
              f"{percentile(values, 99) * 1000:8.0f} {max(values, default=0) * 1000:8.0f} "
              f"{results.errors[name]:7d} {results.limited[name]:6d}")
    error_rate = errors / total if total else 1.0
    print(f"\n{total} requests in {elapsed:.0f}s ({total / elapsed:.1f}/s); error rate {error_rate:.2%}; "
          f"slowest p95 {worst_p95:.0f} ms (target {p95_target_ms} ms)")
    if sum(results.limited.values()):
        print("Some requests were rate limited (429): the test is hitting a per-address limit (nginx's, or the "
              "app's THROTTLE_ANON), not the app's capacity. Raise both for this test's address, or spread the "
              "test over several machines.")
    passed = worst_p95 <= p95_target_ms and error_rate <= max_error_rate
    print('PASS' if passed else 'FAIL')
    return passed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--users', type=int, default=20, help='simulated guests browsing at once')
    parser.add_argument('--duration', type=int, default=60, help='seconds')
    parser.add_argument('--ramp-up', type=int, default=10, help='seconds over which guests arrive')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--p95-ms', type=int, default=800, help='slowest endpoint p95 allowed')
    parser.add_argument('--max-error-rate', type=float, default=0.01)
    args = parser.parse_args(argv)

    results, stop = Results(), threading.Event()
    threads = [threading.Thread(target=guest, args=(args.base_url, args.timeout, results, stop, n), daemon=True)
               for n in range(args.users)]
    print(f"{args.users} guests on {args.base_url} for {args.duration}s (arriving over {args.ramp_up}s)...")
    start = time.perf_counter()
    for thread in threads:
        thread.start()
        time.sleep(args.ramp_up / max(args.users, 1))
    stop.wait(max(0, args.duration - (time.perf_counter() - start)))
    stop.set()
    for thread in threads:
        thread.join(timeout=args.timeout)
    return 0 if report(results, time.perf_counter() - start, args.p95_ms, args.max_error_rate) else 1


if __name__ == '__main__':
    sys.exit(main())
