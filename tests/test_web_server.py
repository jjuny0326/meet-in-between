import threading
import json
import time
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
        for path in ("/", "/styles.css", "/app.js", "/search.js"):
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

    def post(self, payload, headers=None):
        return self.request("/api/recommendations", "POST", json.dumps(payload), headers or {"Content-Type": "application/json"})

    def test_station_tokens_hide_key_and_coordinates_and_recommend_uses_server_values(self):
        station = {"place_name": "테스트역", "address_name": "주소", "x": "127", "y": "37"}
        with patch.object(serve_web, "get_api_key", return_value="never-expose-this"), \
                patch.object(serve_web, "search_stations", return_value=[station]), \
                patch.object(serve_web, "build_recommendation", return_value={"example": True}) as build, \
                patch.object(serve_web, "save_report") as save:
            status, _, body = self.request("/api/stations?query=test")
            self.assertEqual(status, 200)
            result = json.loads(body)["stations"][0]
            self.assertEqual(set(result), {"token", "name", "address"})
            status, _, body = self.post({"station_a": result["token"], "station_b": result["token"], "preferences": ["cafe"]})
            self.assertEqual(status, 200)
            self.assertNotIn(b"never-expose-this", body)
            build.assert_called_once_with(station, station, ["cafe"], "never-expose-this")
            save.assert_called_once()

    def test_invalid_or_expired_selection_never_starts_recommendation(self):
        serve_web.STATIONS["expired"] = (time.monotonic() - 3601, {})
        with patch.object(serve_web, "build_recommendation") as build:
            for token, prefs in (("unknown", ["cafe"]), ("expired", ["cafe"]), ("expired", []), ("expired", ["bad"])):
                self.assertEqual(self.post({"station_a": token, "station_b": token, "preferences": prefs})[0], 400)
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
            self.assertEqual(self.post({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})[0], 429)
            save.assert_not_called()
            self.assertFalse(serve_web.API_LOCK.locked())

    def test_save_failure_still_returns_result(self):
        serve_web.STATIONS["valid"] = (time.monotonic(), {})
        with patch.object(serve_web, "get_api_key", return_value="dummy"), \
                patch.object(serve_web, "build_recommendation", return_value={"example": True}), \
                patch.object(serve_web, "save_report", side_effect=OSError):
            status, _, body = self.post({"station_a": "valid", "station_b": "valid", "preferences": ["cafe"]})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["warning"])


if __name__ == "__main__":
    unittest.main()
