import json
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

from route_cache import RouteCache
import station_search as app

A = {"x":127,"y":37,"place_name":"A"}
B = {"x":128,"y":37,"place_name":"B"}
C = {"x":129,"y":37,"place_name":"C"}
ROUTES = [{"properties":{"totalTime":1800,"transfers":2}}, {"properties":{"totalTime":2700,"transfers":0}}]


class RouteCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.cache = RouteCache(clock=lambda:self.now, timestamp=lambda:"2026-10-15T10:00:00+09:00")
        self.fetch = Mock(return_value=ROUTES)
        self.capacity = Mock()

    def load(self, pairs, key="test"):
        return self.cache.load_batch(pairs, key, self.fetch, self.capacity)

    def test_full_routes_are_reused_without_quota_check_and_cannot_be_mutated(self):
        first, stats = self.load([(A,B)])
        self.assertEqual(stats["api_calls"],1)
        first[0]["routes"][0]["properties"]["totalTime"] = 999
        self.capacity.reset_mock()
        second, stats = self.load([(A,B)])
        self.assertEqual(second[0]["routes"],ROUTES)
        self.assertEqual(stats["cache_hits"],1)
        self.assertEqual(first[0]["fetched_at"],second[0]["fetched_at"])
        self.capacity.assert_not_called()
        self.fetch.assert_called_once()

    def test_direction_key_and_coordinates_are_part_of_cache_key(self):
        self.load([(A,B)])
        self.load([({"x":"127.0","y":"37.00"},B)])
        self.assertEqual(self.fetch.call_count,1)
        self.load([(B,A)])
        self.load([(A,C)])
        self.load([(A,B)],key="another")
        self.assertEqual(self.fetch.call_count,4)
        self.assertNotIn("another",str(list(self.cache.entries)))

    def test_ttl_expires_at_ten_minutes_without_sliding_on_hit(self):
        self.load([(A,B)])
        self.now = 599
        self.assertEqual(self.load([(A,B)])[1]["cache_hits"],1)
        self.now = 600
        self.assertEqual(self.load([(A,B)])[1]["api_calls"],1)
        self.assertEqual(self.fetch.call_count,2)

    def test_only_unique_missing_pairs_require_capacity(self):
        self.load([(A,B)])
        self.capacity.reset_mock()
        _, stats = self.load([(A,B),(A,C),(A,C)])
        self.capacity.assert_called_once_with(1)
        self.assertEqual(stats["cache_hits"],2)
        self.assertEqual(stats["api_calls"],1)

    def test_quota_failure_stops_all_new_calls(self):
        self.load([(A,B)])
        self.capacity.side_effect = app.RouteLimitError("limit")
        with self.assertRaises(app.RouteLimitError):
            self.load([(A,B),(A,C)])
        self.fetch.assert_called_once()

    def test_failed_lookup_is_not_cached_but_completed_pair_is_kept(self):
        self.fetch.side_effect = [ROUTES,RuntimeError("failure"),ROUTES]
        with self.assertRaises(RuntimeError):
            self.load([(A,B),(A,C)])
        _, stats = self.load([(A,B),(A,C)])
        self.assertEqual((stats["cache_hits"],stats["api_calls"]),(1,1))
        self.assertEqual(self.fetch.call_count,3)

    def test_valid_entries_are_reserved_at_batch_start(self):
        self.load([(A,B)])
        self.now = 599
        def fetch(*args):
            self.now = 601
            return ROUTES
        self.fetch.side_effect = fetch
        _, stats = self.load([(A,C),(A,B)])
        self.assertEqual(stats["api_calls"],1)
        self.assertEqual(stats["cache_hits"],1)

    def test_memory_is_bounded_and_new_instance_has_no_cache(self):
        self.cache.max_entries = 2
        self.load([(A,B),(A,C),(B,C)])
        self.assertEqual(len(self.cache.entries),2)
        self.assertEqual(self.load([(A,B)])[1]["api_calls"],1)
        self.cache = RouteCache()
        self.assertEqual(self.load([(A,B)])[1]["api_calls"],1)

    def test_concurrent_identical_requests_fetch_once(self):
        gate = threading.Barrier(2)
        def run():
            gate.wait()
            return self.load([(A,B)])[1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sum(r["api_calls"] for r in results),1)
        self.fetch.assert_called_once()

    def test_three_modes_reuse_all_paths_even_when_daily_quota_is_exhausted(self):
        candidates = [{"x":126+i/100,"y":37,"place_name":f"후보{i}","line_name":"테스트"} for i in range(5)]
        with TemporaryDirectory() as folder, patch.object(app,"BASE_DIR",Path(folder)), \
                patch.object(app,"ROUTE_CACHE",self.cache), \
                patch.object(app,"find_meeting_candidates",return_value=candidates), \
                patch.object(app.requests,"get",return_value=Mock(status_code=200,json=lambda:{"status":"OK","routes":ROUTES})) as network, \
                patch.object(app,"enrich_recommendations",side_effect=lambda rows,*args:[{**row,"rank":i+1} for i,row in enumerate(rows[:3])]), \
                patch.object(app,"analyze_recommendations",return_value={}):
            first = app.build_recommendation(A,B,["cafe"],"test",mode="burden")
            self.assertEqual(first["route_usage"]["api_calls"],10)
            self.assertEqual(first["recommendations"][0]["minutes_a"],30)
            usage = app.read_route_usage()
            self.assertEqual(usage["count"],10)
            usage["count"] = 20
            (Path(folder)/".route_usage.json").write_text(json.dumps(usage))
            fair = app.build_recommendation(A,B,["cafe"],"test",mode="fair")
            transfers = app.build_recommendation(A,B,["cafe"],"test",mode="transfers")
            self.assertEqual(fair["route_usage"]["cache_hits"],10)
            self.assertEqual(transfers["route_usage"]["api_calls"],0)
            self.assertEqual(transfers["recommendations"][0]["minutes_a"],45)
            self.assertEqual(transfers["recommendations"][0]["transfers_a"],0)
            self.assertEqual(network.call_count,10)
            self.assertEqual(app.read_route_usage()["count"],20)
            self.now = 600
            with self.assertRaises(app.RouteLimitError):
                app.build_recommendation(A,B,["cafe"],"test")
            self.assertEqual(network.call_count,10)
