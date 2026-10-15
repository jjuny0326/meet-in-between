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
from recommendation_policy import validate_mode
from station_catalog import suggest as suggest_stations, resolve as resolve_local_station

BASE_DIR = Path(__file__).resolve().parent
# 프로젝트 전체를 공개하지 않고 지정한 파일만 제공합니다.
FILES = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/index.html": ("web/index.html", "text/html; charset=utf-8"),
    "/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
    "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
    "/search.js": ("web/search.js", "text/javascript; charset=utf-8"),
    "/map.js": ("web/map.js", "text/javascript; charset=utf-8"),
    "/theme.js": ("web/theme.js", "text/javascript; charset=utf-8"),
    "/tabs.js": ("web/tabs.js", "text/javascript; charset=utf-8"),
    "/data/latest_comparison.json": ("data/latest_comparison.json", "application/json; charset=utf-8"),
}

# 웹 요청은 순서대로 처리해 호출 기록과 마지막 결과의 충돌을 막습니다.
API_LOCK = threading.Lock()
STATIONS = {}

# 추천 작업 상태. 화면은 작업 번호로 진행 단계와 결과를 조회합니다(폴링).
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_STAGES = ("candidates", "routes", "places", "ai")
JOB_KEEP_SECONDS = 3600
JOB_MAX_KEPT = 20


def update_job(job, **changes):
    with JOBS_LOCK:
        job.update(changes)
        job["updated"] = time.monotonic()


def public_job(job):
    """화면에 보낼 항목만 고릅니다. 내부 시각이나 예외 정보는 보내지 않습니다."""
    with JOBS_LOCK:
        data = {key: job[key] for key in ("job_id", "status", "stage", "message")}
        data["stage_index"] = JOB_STAGES.index(job["stage"]) if job["stage"] in JOB_STAGES else None
        data["stage_count"] = len(JOB_STAGES)
        if job["status"] == "done":
            data.update(report=job["report"], warning=job["warning"])
        elif job["status"] == "error":
            data.update(error=job["error"], error_status=job["error_status"])
        return data


def forget_old_jobs():
    now = time.monotonic()
    with JOBS_LOCK:
        for job_id, job in list(JOBS.items()):
            if job["status"] != "running" and now - job["updated"] > JOB_KEEP_SECONDS:
                del JOBS[job_id]
        finished = [job_id for job_id, job in JOBS.items() if job["status"] != "running"]
        while len(JOBS) > JOB_MAX_KEPT and finished:
            del JOBS[finished.pop(0)]


def run_job(job, stations, preferences, api_key, mode):
    """백그라운드 스레드에서 추천을 계산합니다. 끝나면 요청 스레드가 넘겨준 API_LOCK을 풉니다."""
    try:
        report = build_recommendation(
            *stations, preferences, api_key, mode=mode,
            on_stage=lambda stage, message: update_job(job, stage=stage, message=message),
        )
        warning = None
        try:
            save_report(report)
        except (OSError, ValueError):
            warning = "비교는 완료했지만 파일을 저장하지 못했습니다. 현재 화면에서 결과를 확인하세요."
        update_job(job, status="done", stage="done", message="비교를 마쳤어요.", report=report, warning=warning)
    except RouteLimitError as error:
        update_job(job, status="error", error=str(error), error_status=429)
    except (ValueError, KeyError, TypeError):
        update_job(job, status="error", error="추천 계산에 필요한 정보를 처리하지 못했습니다. 출발역을 다시 선택해 주세요.", error_status=400)
    except RuntimeError as error:
        update_job(job, status="error", error=str(error), error_status=503)
    except Exception:
        # 내부 오류에 포함될 수 있는 인증 정보나 경로는 응답에 넣지 않습니다.
        update_job(job, status="error", error="추천 처리 중 오류가 발생했습니다. 기존 결과는 유지됩니다.", error_status=500)
    finally:
        API_LOCK.release()


def get_api_key():
    key = os.getenv("KAKAO_REST_API_KEY")
    if not key:
        raise RuntimeError(".env에 KAKAO_REST_API_KEY를 설정하고 서버를 다시 시작하세요.")
    return key


class ComparisonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/api/map-config":
            # JavaScript 키는 브라우저용 공개 키입니다. 서버용 키는 절대 반환하지 않습니다.
            key = os.getenv("KAKAO_JAVASCRIPT_KEY", "").strip()
            if key and key in (os.getenv("KAKAO_REST_API_KEY"), os.getenv("GEMINI_API_KEY")):
                key = ""
            self.send_json(200, {"javascript_key": key})
        elif urlsplit(self.path).path == "/api/stations":
            self.handle_api(self.station_search)
        elif urlsplit(self.path).path == "/api/station-suggestions":
            self.station_suggestions()
        elif urlsplit(self.path).path.startswith("/api/recommendations/"):
            self.job_status()
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

    def is_local_request(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin != f"http://{host}") or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json(403, {"error": "로컬 화면에서 요청하세요."})
            return False
        return True

    def handle_api(self, action):
        if not self.is_local_request():
            return
        if not API_LOCK.acquire(blocking=False):
            self.send_json(409, {"error": "다른 검색을 처리 중입니다. 완료 후 다시 시도하세요."})
            return
        # 작업 스레드가 시작되면 락은 그 스레드가 풉니다(self.lock_handed_over).
        self.lock_handed_over = False
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
            if not self.lock_handed_over:
                API_LOCK.release()

    def job_status(self):
        if not self.is_local_request():
            return
        job_id = urlsplit(self.path).path.rsplit("/", 1)[-1]
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            self.send_json(404, {"error": "추천 작업을 찾을 수 없어요. 서버가 재시작됐다면 ‘결과 다시 읽기’로 마지막 결과를 확인하세요."})
            return
        self.send_json(200, public_job(job))

    def station_suggestions(self):
        """로컬 역 목록 자동완성. 외부 API를 쓰지 않으므로 추천 작업 중에도 응답합니다."""
        if not self.is_local_request():
            return
        query = parse_qs(urlsplit(self.path).query).get("query", [""])[0]
        self.send_json(200, {"stations": suggest_stations(query)})

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
        mode = validate_mode(payload.get("recommendation_mode", "burden"))
        preferences = payload["preferences"]
        if not isinstance(preferences, list) or not 1 <= len(preferences) <= 3 or any(p not in ("cafe", "food", "culture") for p in preferences):
            raise ValueError()
        stations = []
        for key in ("station_a", "station_b"):
            # 자동완성으로 고른 역(local-번호)은 로컬 목록에서, 카카오 검색으로 고른 역은 임시 선택 번호로 찾습니다.
            local = resolve_local_station(payload[key])
            if local is not None:
                stations.append(local)
                continue
            created, station = STATIONS[payload[key]]
            if time.monotonic() - created > 3600:
                raise ValueError()
            stations.append(station)
        api_key = get_api_key()
        # 입력 검증까지는 요청 안에서 끝내고, 오래 걸리는 계산은 작업으로 넘깁니다.
        forget_old_jobs()
        job = {"job_id": uuid.uuid4().hex, "status": "running", "stage": "queued",
               "message": "추천을 준비하고 있어요.", "report": None, "warning": None,
               "error": None, "error_status": None, "updated": time.monotonic()}
        with JOBS_LOCK:
            JOBS[job["job_id"]] = job
        worker = threading.Thread(target=run_job, args=(job, stations, list(dict.fromkeys(preferences)), api_key, mode), daemon=True)
        worker.start()
        self.lock_handed_over = True
        self.send_json(202, public_job(job))

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
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://dapi.kakao.com https://t1.daumcdn.net https://t1.kakaocdn.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://dapi.kakao.com; img-src 'self' data: https://*.daumcdn.net https://*.kakaocdn.net; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; upgrade-insecure-requests")
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
