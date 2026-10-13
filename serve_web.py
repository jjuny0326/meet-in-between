"""웹 검색과 비교 화면을 제공하는 로컬 서버. 실행: python serve_web.py"""

import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from dotenv import load_dotenv
from station_search import search_stations, build_recommendation, RouteLimitError
from comparison import save_report

BASE_DIR = Path(__file__).resolve().parent
# 프로젝트 전체를 공개하지 않고 지정한 파일만 제공합니다.
FILES = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/index.html": ("web/index.html", "text/html; charset=utf-8"),
    "/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
    "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
    "/search.js": ("web/search.js", "text/javascript; charset=utf-8"),
    "/data/latest_comparison.json": ("data/latest_comparison.json", "application/json; charset=utf-8"),
}

# 웹 요청은 순서대로 처리해 호출 기록과 마지막 결과의 충돌을 막습니다.
API_LOCK = threading.Lock()
STATIONS = {}


def get_api_key():
    key = os.getenv("KAKAO_REST_API_KEY")
    if not key:
        raise RuntimeError(".env에 KAKAO_REST_API_KEY를 설정하고 서버를 다시 시작하세요.")
    return key


class ComparisonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/api/stations":
            self.handle_api(self.station_search)
        else:
            self.send_file()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/recommendations":
            self.send_error(404)
            return
        self.handle_api(self.recommend)

    def send_json(self, status, data):
        content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def handle_api(self, action):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin != f"http://{host}") or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json(403, {"error": "로컬 화면에서 요청하세요."})
            return
        if not API_LOCK.acquire(blocking=False):
            self.send_json(409, {"error": "다른 검색을 처리 중입니다. 완료 후 다시 시도하세요."})
            return
        try:
            action()
        except RouteLimitError as error:
            self.send_json(429, {"error": str(error)})
        except (ValueError, KeyError, TypeError):
            self.send_json(400, {"error": "출발역을 다시 검색·선택하고 활동을 1개 이상 선택하세요."})
        except RuntimeError as error:
            self.send_json(503, {"error": str(error)})
        except Exception:
            # 내부 오류에 포함될 수 있는 인증 정보나 경로는 응답에 넣지 않습니다.
            self.send_json(500, {"error": "추천 처리 중 오류가 발생했습니다. 기존 결과는 유지됩니다."})
        finally:
            API_LOCK.release()

    def station_search(self):
        query = parse_qs(urlsplit(self.path).query).get("query", [""])[0]
        stations = search_stations(query, get_api_key())
        now = time.monotonic()
        for token, (created, _) in list(STATIONS.items()):
            if now - created > 3600:
                del STATIONS[token]
        results = []
        for station in stations:
            token = uuid.uuid4().hex
            STATIONS[token] = (now, station)
            results.append({"token": token, "name": station["place_name"], "address": station.get("address_name", "")})
        while len(STATIONS) > 200:
            del STATIONS[next(iter(STATIONS))]
        self.send_json(200, {"stations": results})

    def recommend(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError()
        length = int(self.headers.get("Content-Length", "0"))
        if not 1 <= length <= 8192:
            raise ValueError()
        payload = json.loads(self.rfile.read(length))
        preferences = payload["preferences"]
        if not isinstance(preferences, list) or not 1 <= len(preferences) <= 3 or any(p not in ("cafe", "food", "culture") for p in preferences):
            raise ValueError()
        stations = []
        for key in ("station_a", "station_b"):
            created, station = STATIONS[payload[key]]
            if time.monotonic() - created > 3600:
                raise ValueError()
            stations.append(station)
        report = build_recommendation(*stations, list(dict.fromkeys(preferences)), get_api_key())
        warning = None
        try:
            save_report(report)
        except (OSError, ValueError):
            warning = "비교는 완료했지만 파일을 저장하지 못했습니다. 현재 화면에서 결과를 확인하세요."
        self.send_json(200, {"report": report, "warning": warning})

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
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description="우리 사이 로컬 비교 화면")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ComparisonHandler)
    except OSError:
        raise SystemExit("포트를 사용할 수 없습니다. --port 8001 등 다른 포트로 실행하세요.")
    print(f"우리 사이: http://127.0.0.1:{server.server_port}", flush=True)
    print("브라우저에서 출발역을 검색하세요. 새 추천은 외부 API를 사용합니다. 종료: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
