import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

import json
from datetime import datetime, timedelta, timezone

from math import radians, sin, cos, asin, sqrt, isfinite

from comparison import (
    KOREA_TIME, select_preferences, enrich_recommendations,
    analyze_recommendations, print_report, save_report, load_report,
)

BASE_DIR = Path(__file__).resolve().parent


class RouteLimitError(RuntimeError):
    """자체 경로 조회 한도가 부족할 때 발생합니다."""


def search_stations(station_name, api_key):
    """입력/출력 없이 역 검색 결과를 반환하므로 웹에서도 사용합니다."""
    if not isinstance(station_name, str) or not 1 <= len(station_name.strip()) <= 80:
        raise ValueError("역 이름을 1~80자로 입력하세요.")
    station_name = station_name.strip()

    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {
        "query": station_name,
        "category_group_code": "SW8",
        "size": 5,
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10,
        )
    except requests.RequestException:
        raise RuntimeError("역 검색 서버에 연결하지 못했습니다.") from None

    if response.status_code != 200:
        raise RuntimeError("역 검색에 실패했습니다. 키 설정과 사용량을 확인하세요.")
    try:
        stations = response.json()["documents"]
        if not isinstance(stations, list):
            raise ValueError()
        for station in stations:
            if not isinstance(station["place_name"], str) or not station["place_name"]:
                raise ValueError()
            if not (-180 <= float(station["x"]) <= 180 and -90 <= float(station["y"]) <= 90):
                raise ValueError()
        return stations
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("역 검색 응답 형식이 올바르지 않습니다.") from None


def select_station(person_name, api_key):
    station_name = input(f"{person_name}의 출발역 이름을 입력하세요: ").strip()
    stations = search_stations(station_name, api_key)

    if not stations:
        raise SystemExit("검색된 역이 없습니다.")

    for index, station in enumerate(stations, start=1):
        print(f"{index}. {station['place_name']}")
        print(f"   주소: {station['address_name']}")

    try:
        choice = int(input("출발역 번호를 선택하세요: "))
    except ValueError:
        raise SystemExit("번호는 정수로 입력해야 합니다.")

    if not 1 <= choice <= len(stations):
        raise SystemExit("목록에 있는 번호를 선택해야 합니다.")

    selected_station = stations[choice - 1]
    print("선택한 역:", selected_station["place_name"])
    print("경도:", selected_station["x"])
    print("위도:", selected_station["y"])
    print()

    return selected_station

# 하루 경로 조회 횟수 제한
def read_route_usage():
    usage_path = BASE_DIR / ".route_usage.json"
    korea_time = timezone(timedelta(hours=9))
    today = datetime.now(korea_time).date().isoformat()

    try:
        if usage_path.exists():
            usage = json.loads(usage_path.read_text(encoding="utf-8"))

            # 기록이 손상됐다면 초기화하지 않고 중단
            if (
                    not isinstance(usage, dict)
                    or not isinstance(usage.get("date"), str)
                    or type(usage.get("count")) is not int
                    or usage["count"] < 0
            ):
                raise ValueError("잘못된 호출 기록")
        else:
            usage = {"date": today, "count": 0}

        recorded_day = datetime.strptime(usage["date"], "%Y-%m-%d").date()
        if recorded_day > datetime.now(korea_time).date():
            raise ValueError("미래 날짜의 호출 기록")
        if usage["date"] != today:
            usage = {"date": today, "count": 0}
        return usage
    except (OSError, ValueError):
        raise RuntimeError("호출 기록을 읽지 못해 요청을 중단합니다.") from None


def ensure_route_capacity(required):
    remaining = max(0, 20 - read_route_usage()["count"])
    if remaining < required:
        raise RouteLimitError(f"경로 조회가 {required}회 필요하지만 오늘 남은 횟수는 {remaining}회입니다. 저장 결과를 보거나 내일 다시 시도하세요.")


def reserve_route_call():
    ensure_route_capacity(1)
    usage = read_route_usage()
    usage["count"] += 1
    try:
        temporary = BASE_DIR / ".route_usage.tmp"
        temporary.write_text(
            json.dumps(usage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(BASE_DIR / ".route_usage.json")
    except (OSError, ValueError):
        raise RuntimeError("호출 기록을 저장하지 못해 요청을 중단합니다.") from None



# 선택한 역 사이의 대중교통 이동시간 조회
def get_transit_routes(start_station, end_station, api_key):
    url = "https://dapi.kakao.com/v2/routing/publictraffic"
    headers = {"Authorization": f"KakaoAK {api_key}"}

    params = {
        "start_x": start_station["x"],
        "start_y": start_station["y"],
        "end_x": end_station["x"],
        "end_y": end_station["y"],
    }

    reserve_route_call()

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10,
        )
    except requests.RequestException:
        raise RuntimeError("경로 조회 중 통신 오류가 발생했습니다.") from None


    if response.status_code != 200:
        raise RuntimeError("경로 요청에 실패했습니다. 키 설정과 사용량을 확인하세요.")

    try:
        data = response.json()
        if data.get("status") != "OK":
            raise ValueError()
        routes = data["routes"]
        if not isinstance(routes, list) or not routes:
            raise ValueError()
        for route in routes:
            properties = route["properties"]
            duration, transfers = properties["totalTime"], properties["transfers"]
            if type(duration) not in (int, float) or not isfinite(duration) or duration < 0:
                raise ValueError()
            if type(transfers) is not int or transfers < 0:
                raise ValueError()
        return routes
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("사용할 수 있는 경로가 없습니다. 출발역을 확인하세요.") from None

# 두 좌표 사이의 직선거리를 km로 계산
def distance_km(station_a, station_b):
    lat_a = radians(float(station_a["y"]))
    lat_b = radians(float(station_b["y"]))
    delta_lat = lat_b - lat_a
    delta_lon = radians(
        float(station_b["x"]) - float(station_a["x"])
    )

    value = (
            sin(delta_lat / 2) ** 2
            + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )

    return 6371 * 2 * asin(sqrt(min(1.0, max(0.0, value))))

# 저장한 역 목록에서 후보 고르기
def find_meeting_candidates(station_a, station_b, limit=5):
    file_path = (
            Path(__file__).resolve().parent
            / "data"
            / "capital_stations.json"
    )

    stations = json.loads(file_path.read_text(encoding="utf-8"))
    ranked = []

    for station in stations:
        distance_a = distance_km(station_a, station)
        distance_b = distance_km(station_b, station)

        # 두 사람 중 더 멀리 이동하는 사람의 거리를 기준으로 비교
        score = max(distance_a, distance_b)
        ranked.append((score, station))

    ranked.sort(key=lambda item: item[0])

    candidates = []

    for score, station in ranked:
        # 같은 환승역 주변으로 후보가 몰리지 않도록 간격 확보
        too_close = any(
            distance_km(station, selected) < 1.0
            for selected in candidates
        )

        if too_close:
            continue

        candidates.append(station)

        if len(candidates) == limit:
            break

    return candidates

def show_and_save_report(report):
    print_report(report)
    try:
        save_report(report)
    except (OSError, ValueError):
        print("결과 파일을 저장하지 못했습니다. 위의 비교 결과를 확인하세요.")
    else:
        print("\n비교 결과 저장 완료: data/latest_comparison.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="두 사람의 만남 후보 3곳 비교")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--saved", action="store_true", help="API 호출 없이 저장 결과 보기")
    modes.add_argument("--explain-saved", action="store_true", help="저장 결과의 AI 설명만 다시 작성")
    args = parser.parse_args(argv)
    BASE_DIR = Path(__file__).resolve().parent
    load_dotenv(BASE_DIR / ".env")

    if args.saved or args.explain_saved:
        try:
            report = load_report()
            if args.explain_saved:
                report["analysis"] = analyze_recommendations(
                    report["recommendations"], report["preferences"]
                )
                return show_and_save_report(report)
            print_report(report)
            return report
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise SystemExit("저장된 비교 결과가 없거나 형식이 잘못되었습니다. 먼저 일반 실행으로 결과를 만드세요.")
    api_key = os.getenv("KAKAO_REST_API_KEY")

    if not api_key:
        raise SystemExit("API 키가 없습니다. .env를 확인하세요.")

    print("카카오 API 키를 읽었습니다.")
    preferences = select_preferences()

    station_a = select_station("첫 번째 사람", api_key)
    station_b = select_station("두 번째 사람", api_key)

    print("첫 번째 출발역:", station_a["place_name"])
    print("두 번째 출발역:", station_b["place_name"])

    return show_and_save_report(build_recommendation(station_a, station_b, preferences, api_key, progress=print))


def build_recommendation(station_a, station_b, preferences, api_key, progress=None):
    """두 출발역과 활동으로 결과를 계산합니다. 입력과 파일 저장은 호출자가 담당합니다."""
    candidates = find_meeting_candidates(station_a, station_b)

    notify = progress or (lambda message: None)
    notify("\n자동으로 선정한 만남 후보 (직선거리 기준)")

    if not candidates:
        raise RuntimeError("선정할 수 있는 후보역이 없습니다.")

    for index, station in enumerate(candidates, start=1):
        notify(
            f"{index}. {station['place_name']} "
            f"({station['line_name']})"
        )

    ensure_route_capacity(len(candidates) * 2)

    # 후보별 이동시간을 비교해서 상위 3곳을 출력
    results = []

    for candidate in candidates:
        notify(f"\n이동시간 확인 중: {candidate['place_name']}")

        routes_a = get_transit_routes(station_a, candidate, api_key)
        routes_b = get_transit_routes(station_b, candidate, api_key)

        fastest_a = min(
            routes_a,
            key=lambda route: route["properties"]["totalTime"]
        )
        fastest_b = min(
            routes_b,
            key=lambda route: route["properties"]["totalTime"]
        )

        minutes_a = fastest_a["properties"]["totalTime"] / 60
        minutes_b = fastest_b["properties"]["totalTime"] / 60

        results.append({
            "station": candidate,
            "minutes_a": minutes_a,
            "minutes_b": minutes_b,
            "transfers_a": fastest_a["properties"]["transfers"],
            "transfers_b": fastest_b["properties"]["transfers"],
            "total": minutes_a + minutes_b,
            "difference": abs(minutes_a - minutes_b),
            "longest": max(minutes_a, minutes_b),
        })

    results.sort(
        key=lambda result: (result["longest"], result["total"])
    )

    # 같은 구조를 콘솔 출력, 저장 파일, 웹 화면에서 함께 사용합니다.
    recommendations = enrich_recommendations(results, preferences, api_key)
    report = {
        "schema_version": 1,
        "origins": [station_a["place_name"], station_b["place_name"]],
        "collected_at": datetime.now(KOREA_TIME).isoformat(),
        "preferences": preferences,
        "recommendations": recommendations,
        "analysis": analyze_recommendations(recommendations, preferences),
    }
    return report

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
