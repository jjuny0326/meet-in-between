import threading
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

    def request(self, path, method="GET"):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_static_screen_and_head(self):
        for path in ("/", "/styles.css", "/app.js"):
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


if __name__ == "__main__":
    unittest.main()
