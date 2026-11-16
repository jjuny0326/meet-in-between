import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

import station_search as app


class StationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.patch = patch.object(app, "BASE_DIR", self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_insufficient_quota_stops_before_network_or_ai(self):
        (self.base / ".route_usage.json").write_text(json.dumps({"date": datetime.now(app.KOREA_TIME).date().isoformat(), "count": 11}))
        with patch.object(app, "ROUTE_CACHE", app.RouteCache()), \
                patch.object(app, "find_meeting_candidates", return_value=[{"place_name": "후보", "line_name": "1", "x":127+i/100,"y":37} for i in range(5)]), \
                patch.object(app, "get_transit_routes") as routes, patch.object(app, "analyze_recommendations") as ai:
            with self.assertRaises(app.RouteLimitError):
                app.build_recommendation({"x":128,"y":37}, {"x":129,"y":37}, ["cafe"], "dummy")
            routes.assert_not_called()
            ai.assert_not_called()

    def test_place_search_uses_keyword_first_and_normalizes_shape(self):
        keyword = [{"place_name": "스타벅스 강남역점", "road_address_name": "서울 강남구 강남대로 390", "address_name": "역삼동 1", "x": "127.02", "y": "37.49"},
                   {"place_name": "", "x": "127", "y": "37"}]  # 이름 없는 결과는 버립니다.
        with patch.object(app, "kakao_local", return_value=keyword) as local:
            places = app.search_places("  스타벅스 강남  ", "dummy")
        local.assert_called_once_with("keyword", {"query": "스타벅스 강남", "size": 5}, "dummy")
        self.assertEqual(places, [{"place_name": "스타벅스 강남역점", "address_name": "서울 강남구 강남대로 390", "x": "127.02", "y": "37.49"}])

    def test_place_search_falls_back_to_address_only_when_keyword_is_empty(self):
        address = [{"address_name": "서울 강남구 테헤란로 152", "x": "127.03", "y": "37.50"}]
        with patch.object(app, "kakao_local", side_effect=[[], address]) as local:
            places = app.search_places("서울 강남구 테헤란로 152", "dummy")
        self.assertEqual([call.args[0] for call in local.call_args_list], ["keyword", "address"])
        self.assertEqual(places[0]["place_name"], "서울 강남구 테헤란로 152")
        with patch.object(app, "kakao_local") as local:
            for value in ("", " " * 3, "가" * 81, None):
                with self.assertRaises(ValueError):
                    app.search_places(value, "dummy")
            local.assert_not_called()

    def test_transfer_station_gets_bonus_and_unknown_station_is_not_penalized(self):
        a, b = {"x": 127.0, "y": 37.5}, {"x": 127.2, "y": 37.5}
        middle = {"x": 127.1, "y": 37.5}
        distance = app.distance_km(a, middle)
        counts = {"한줄": 1, "두줄": 2, "세줄": 3}  # 없는 이름은 0 → 노선 1개로 봅니다.
        with patch.object(app, "line_counts", return_value=__import__("collections").Counter(counts)):
            score = lambda name: app.candidate_score(a, b, {**middle, "place_name": name})
            self.assertAlmostEqual(score("한줄"), distance)
            self.assertAlmostEqual(score("두줄역"), distance - app.HUB_BONUS_KM)
            self.assertAlmostEqual(score("세줄"), distance - 2 * app.HUB_BONUS_KM)
            self.assertAlmostEqual(score("목록에없는역"), distance)

    def test_candidates_prefer_transfer_station_within_bonus_distance(self):
        # 실제 역 목록: 양주역↔청량리역은 가산점 덕분에 도봉산(1·7호선)이 방학역보다 앞에 옵니다.
        stations = {s["place_name"]: s for s in json.loads((Path(app.__file__).parent / "data" / "capital_stations.json").read_text(encoding="utf-8"))}
        names = [s["place_name"] for s in app.find_meeting_candidates(stations["양주역"], stations["청량리역"])]
        self.assertEqual(len(names), 5)
        self.assertLess(names.index("도봉산"), names.index("방학역"))

    def test_corrupt_or_future_usage_is_not_reset(self):
        usage = self.base / ".route_usage.json"
        tomorrow = (datetime.now(app.KOREA_TIME) + timedelta(days=1)).date().isoformat()
        for value in ("bad", json.dumps({"date": tomorrow, "count": 0})):
            usage.write_text(value)
            with self.assertRaises(RuntimeError):
                app.reserve_route_call()
            self.assertEqual(usage.read_text(), value)

    def test_failed_route_call_still_consumes_one_attempt(self):
        station = {"x": 127, "y": 37}
        with patch.object(app.requests, "get", return_value=Mock(status_code=503)) as get:
            with self.assertRaises(RuntimeError):
                app.get_transit_routes(station, station, "dummy")
            self.assertEqual(app.read_route_usage()["count"], 1)
            get.assert_called_once()

    def test_invalid_search_input_does_not_call_network(self):
        with patch.object(app.requests, "get") as get:
            for value in ("", " " * 5, "a" * 81, None):
                with self.assertRaises(ValueError):
                    app.search_stations(value, "dummy")
            get.assert_not_called()

    def test_malformed_station_response_has_safe_error(self):
        response = Mock(status_code=200)
        response.json.return_value = {"documents": [{"place_name": "역", "x": "nan", "y": 37}]}
        with patch.object(app.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "응답 형식"):
                app.search_stations("역", "dummy")
