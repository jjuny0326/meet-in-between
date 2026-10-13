"""외부 호출·사용량 변경 없이 웹을 점검합니다: python tests/preview_web.py

테스트 서버 주소는 http://127.0.0.1:8002 입니다. 종료: Ctrl+C.
"""
import sys
from pathlib import Path
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve_web
import station_search
import comparison


def stations(query, key):
    if query == "없음":
        return []
    return [{"place_name": f"{query} {line} (테스트)", "address_name": "가상 검색 결과", "x": 127, "y": 37} for line in ("1호선", "2호선")]


def routes(*args):
    time.sleep(0.2)
    return [{"properties": {"totalTime": 2400, "transfers": 1}}]


class PreviewHandler(serve_web.ComparisonHandler):
    def send_file(self, head_only=False):
        if self.path == "/data/latest_comparison.json":
            self.send_error(404)
        else:
            super().send_file(head_only)


if __name__ == "__main__":
    candidates = [{"place_name": f"테스트 후보{i}역", "line_name": "가상 노선", "x": 127, "y": 37} for i in range(1, 6)]
    with patch.object(serve_web, "get_api_key", return_value="test-only"), \
            patch.object(serve_web, "search_stations", side_effect=stations), \
            patch.object(serve_web, "save_report"), \
            patch.object(station_search, "find_meeting_candidates", return_value=candidates), \
            patch.object(station_search, "ensure_route_capacity"), \
            patch.object(station_search, "get_transit_routes", side_effect=routes), \
            patch.object(comparison, "search_nearby_places", return_value=[]), \
            patch.object(station_search, "analyze_recommendations", side_effect=lambda items, prefs, mode="burden": comparison.basic_analysis(items, prefs, "오프라인 테스트: 실제 추천 정보가 아닙니다.", mode)), \
            patch.object(comparison.requests, "get", side_effect=AssertionError("외부 호출 금지")), \
            patch.object(comparison.requests, "post", side_effect=AssertionError("외부 호출 금지")):
        server = serve_web.ThreadingHTTPServer(("127.0.0.1", 8002), PreviewHandler)
        print("OFFLINE TEST: http://127.0.0.1:8002", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
