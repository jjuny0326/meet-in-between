import threading
import json
import time
import os
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

import serve_web


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve_web.ThreadingHTTPServer(("127.0.0.1", 0), serve_web.ComparisonHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, method="GET", body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_static_screen_and_head(self):
        for path in ("/", "/styles.css", "/app.js", "/search.js", "/map.js", "/theme.js", "/tabs.js"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(self.request("/", "HEAD")[2], b"")

    def test_private_files_and_traversal_are_not_served(self):
        for path in ("/.env", "/.ai_usage.json", "/comparison.py", "/../.env", "/%2e%2e/.env", "/data/"):
            with self.subTest(path=path), patch.object(serve_web.Path, "read_bytes") as read:
                self.assertEqual(self.request(path)[0], 404)
                read.assert_not_called()

    def test_snapshot_route_and_missing_file(self):
        with patch.object(serve_web.Path, "read_bytes", return_value=b'{"schema_version":1}'):
            status, headers, body = self.request("/data/latest_comparison.json")
            self.assertEqual(status, 200)
            self.assertIn("application/json", headers["Content-Type"])
        with patch.object(serve_web.Path, "read_bytes", side_effect=FileNotFoundError):
            self.assertEqual(self.request("/data/latest_comparison.json")[0], 404)

    def test_map_config_only_exposes_javascript_key(self):
        with patch.dict(os.environ, {"KAKAO_JAVASCRIPT_KEY": "public-js", "KAKAO_REST_API_KEY": "private-rest", "GEMINI_API_KEY": "private-ai"}, clear=True):
            status, _, body = self.request("/api/map-config")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"javascript_key": "public-js"})
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(json.loads(self.request("/api/map-config")[2]), {"javascript_key": ""})
        with patch.dict(os.environ, {"KAKAO_JAVASCRIPT_KEY": "private", "KAKAO_REST_API_KEY": "private"}, clear=True):
            self.assertEqual(json.loads(self.request("/api/map-config")[2]), {"javascript_key": ""})

    def post(self, payload, headers=None):
        return self.request("/api/recommendations", "POST", json.dumps(payload), headers or {"Content-Type": "application/json"})

    def start_job(self, payload):
        status, _, body = self.post(payload)
        self.assertEqual(status, 202)
        return json.loads(body)

    def wait_job(self, job_id, timeout=3):
        """작업이 끝날 때까지 상태 API를 조회합니다(화면의 폴링과 같은 방식)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, _, body = self.request(f"/api/recommendations/{job_id}")
            self.assertEqual(status, 200)
            job = json.loads(body)
            if job["status"] != "running":
                return job
            time.sleep(0.02)
        self.fail("작업이 제시간에 끝나지 않았습니다.")

    def test_station_tokens_hide_key_and_coordinates_and_recommend_uses_server_values(self):
        station = {"place_name": "테스트역", "address_name": "주소", "x": "127", "y": "37"}
        other = {"place_name": "다른역", "address_name": "주소", "x": "127.1", "y": "37.1"}
        with patch.object(serve_web, "get_api_key", return_value="never-expose-this"), \
                patch.object(serve_web, "search_stations", return_value=[station, other]), \
                patch.object(serve_web, "build_recommendation", return_value={"example": True}) as build, \
                patch.object(serve_web, "save_report") as save:
            status, _, body = self.request("/api/stations?query=test")
            self.assertEqual(status, 200)
            result, second = json.loads(body)["stations"]
            self.assertEqual(set(result), {"token", "name", "address"})
            started = self.start_job({"station_a": result["token"], "station_b": second["token"], "preferences": ["cafe"]})
            job = self.wait_job(started["job_id"])
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["report"], {"example": True})
            self.assertNotIn("never-expose-this", json.dumps(job, ensure_ascii=False))
            build.assert_called_once()
            self.assertEqual(build.call_args.args, (station, other, ["cafe"], "never-expose-this"))
            self.assertEqual(build.call_args.kwargs["mode"], "burden")
            self.assertTrue(callable(build.call_args.kwargs["on_stage"]))
            save.assert_called_once()

    def test_invalid_or_expired_selection_never_starts_recommendation(self):
        serve_web.STATIONS["expired"] = (time.monotonic() - 3601, {})
        with patch.object(serve_web, "build_recommendation") as build:
            for token, prefs in (("unknown", ["cafe"]), ("expired", ["cafe"]), ("expired", []), ("expired", ["bad"])):
                self.assertEqual(self.post({"station_a": token, "station_b": token, "preferences": prefs})[0], 400)
            build.assert_not_called()

    def test_recommendation_mode_is_validated_and_passed_to_calculation(self):
        serve_web.STATIONS["valid"] = (time.monotonic(), {})
        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", return_value={}) as build, \
                patch.object(serve_web, "save_report"):
            for mode in ("fair", "transfers"):
                started = self.start_job({"station_a":"valid", "station_b":"valid", "preferences":["cafe"], "recommendation_mode":mode})
                self.assertEqual(self.wait_job(started["job_id"])["status"], "done")
                self.assertEqual(build.call_args.kwargs["mode"], mode)
            build.reset_mock()
            for mode in ("unknown", None, ["fair"]):
                self.assertEqual(self.post({"recommendation_mode":mode})[0], 400)
            build.assert_not_called()

    def test_foreign_origin_and_concurrent_request_rejected_before_api(self):
        with patch.object(serve_web, "search_stations") as search:
            self.assertEqual(self.request("/api/stations?query=x", headers={"Origin": "https://example.com"})[0], 403)
            with serve_web.API_LOCK:
                self.assertEqual(self.request("/api/stations?query=x")[0], 409)
            search.assert_not_called()

    def test_quota_failure_preserves_snapshot_and_releases_lock(self):
        serve_web.STATIONS["valid"] = (time.monotonic(), {})
        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", side_effect=serve_web.RouteLimitError("한도 부족")), \
                patch.object(serve_web, "save_report") as save:
            job = self.wait_job(self.start_job({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})["job_id"])
            self.assertEqual((job["status"], job["error_status"], job["error"]), ("error", 429, "한도 부족"))
            self.assertNotIn("report", job)
            save.assert_not_called()
            self.assertFalse(serve_web.API_LOCK.locked())

    def test_save_failure_still_returns_result(self):
        serve_web.STATIONS["valid"] = (time.monotonic(), {})
        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", return_value={"example": True}), \
                patch.object(serve_web, "save_report", side_effect=OSError):
            job = self.wait_job(self.start_job({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})["job_id"])
            self.assertEqual(job["status"], "done")
            self.assertTrue(job["warning"])

    def test_job_reports_real_stage_and_blocks_other_requests_until_done(self):
        serve_web.STATIONS["valid"] = (time.monotonic(), {})
        reached, release = threading.Event(), threading.Event()

        def slow_build(*args, on_stage, **kwargs):
            on_stage("routes", "경로를 새로 조회하고 있어요 · 1번째")
            reached.set()
            release.wait(3)
            return {"example": True}

        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", side_effect=slow_build), \
                patch.object(serve_web, "save_report"), \
                patch.object(serve_web, "search_stations") as search:
            started = self.start_job({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})
            self.assertTrue(reached.wait(3))
            status, _, body = self.request(f"/api/recommendations/{started['job_id']}")
            running = json.loads(body)
            self.assertEqual((status, running["status"], running["stage"], running["stage_index"]), (200, "running", "routes", 1))
            self.assertIn("1번째", running["message"])
            self.assertNotIn("report", running)
            # 작업 중에는 새 추천과 역 검색을 거부합니다.
            self.assertEqual(self.post({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})[0], 409)
            self.assertEqual(self.request("/api/stations?query=x")[0], 409)
            search.assert_not_called()
            release.set()
            self.assertEqual(self.wait_job(started["job_id"])["status"], "done")
            self.assertFalse(serve_web.API_LOCK.locked())

    def test_local_suggestions_never_call_kakao_and_hide_coordinates(self):
        with patch.object(serve_web, "search_stations") as search, patch.object(serve_web, "get_api_key") as key:
            status, _, body = self.request("/api/station-suggestions?query=%EA%B0%95%EB%82%A8")  # 강남
            self.assertEqual(status, 200)
            stations = json.loads(body)["stations"]
            self.assertTrue(stations)
            self.assertEqual(stations[0]["name"], "강남역")
            self.assertTrue(all(set(item) == {"token", "name", "line"} for item in stations))
            self.assertEqual(json.loads(self.request("/api/station-suggestions?query=")[2])["stations"], [])
            self.assertEqual(self.request("/api/station-suggestions?query=x", headers={"Origin": "https://example.com"})[0], 403)
            search.assert_not_called()
            key.assert_not_called()

    def test_recommend_accepts_local_station_tokens(self):
        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", return_value={"example": True}) as build, \
                patch.object(serve_web, "save_report"):
            job = self.wait_job(self.start_job({"station_a": "local-0", "station_b": "local-1", "preferences": ["cafe"]})["job_id"])
            self.assertEqual(job["status"], "done")
            station = build.call_args.args[0]
            self.assertEqual(station["place_name"], "신사역 신분당선")
            self.assertIsInstance(station["x"], float)
            build.reset_mock()
            for token in ("local-999999", "local-", "local-abc"):
                self.assertEqual(self.post({"station_a": token, "station_b": "local-0", "preferences": ["cafe"]})[0], 400)
            build.assert_not_called()

    def test_same_station_is_rejected_before_any_api_call(self):
        import station_catalog
        line2, sinbundang = (item["token"] for item in station_catalog.suggest("강남")[:2])
        with patch.object(serve_web, "get_api_key") as key, patch.object(serve_web, "build_recommendation") as build:
            for a, b in (("local-0", "local-0"), (line2, sinbundang)):
                status, _, body = self.post({"station_a": a, "station_b": b, "preferences": ["cafe"]})
                self.assertEqual(status, 400)
                self.assertIn("출발역이 같아요", json.loads(body)["error"])
            key.assert_not_called()
            build.assert_not_called()
        self.assertTrue(serve_web.same_station({"place_name": "강남역 2호선", "x": 127.0276, "y": 37.4979},
                                               {"place_name": "강남역 신분당선", "x": 127.0281, "y": 37.4959}))
        self.assertTrue(serve_web.same_station({"place_name": "A", "x": 127.0, "y": 37.0}, {"place_name": "B", "x": 127.001, "y": 37.001}))
        self.assertFalse(serve_web.same_station({"place_name": "신사역 신분당선", "x": 127.0198, "y": 37.5161},
                                                {"place_name": "논현역 신분당선", "x": 127.0214, "y": 37.5111}))
        self.assertFalse(serve_web.same_station({}, {}))

    def test_unknown_job_and_foreign_origin_on_status(self):
        self.assertEqual(self.request("/api/recommendations/unknown")[0], 404)
        self.assertEqual(self.request("/api/recommendations/unknown", headers={"Origin": "https://example.com"})[0], 403)


if __name__ == "__main__":
    unittest.main()
