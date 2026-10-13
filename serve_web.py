"""저장 결과와 웹 화면만 제공하는 로컬 서버. 실행: python serve_web.py"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent
# 프로젝트 전체를 공개하지 않고 지정한 파일만 제공합니다.
FILES = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/index.html": ("web/index.html", "text/html; charset=utf-8"),
    "/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
    "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
    "/data/latest_comparison.json": ("data/latest_comparison.json", "application/json; charset=utf-8"),
}


class ComparisonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_file()

    def do_HEAD(self):
        self.send_file(head_only=True)

    def send_file(self, head_only=False):
        route = FILES.get(urlsplit(self.path).path)
        if route is None:
            self.send_error(404, "Not found")
            return
        filename, content_type = route
        try:
            content = (BASE_DIR / filename).read_bytes()
        except FileNotFoundError:
            self.send_error(404, "File not found")
            return
        except OSError:
            self.send_error(503, "File unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description="우리 사이 로컬 비교 화면")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ComparisonHandler)
    except OSError:
        raise SystemExit("포트를 사용할 수 없습니다. --port 8001 등 다른 포트로 실행하세요.")
    print(f"우리 사이: http://127.0.0.1:{server.server_port}", flush=True)
    print("저장된 결과만 읽습니다. 종료: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
