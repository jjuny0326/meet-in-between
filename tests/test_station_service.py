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
        with patch.object(app, "find_meeting_candidates", return_value=[{"place_name": "후보", "line_name": "1"}] * 5), \
                patch.object(app, "get_transit_routes") as routes, patch.object(app, "analyze_recommendations") as ai:
            with self.assertRaises(app.RouteLimitError):
                app.build_recommendation({}, {}, ["cafe"], "dummy")
            routes.assert_not_called()
            ai.assert_not_called()

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
