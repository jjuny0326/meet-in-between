"""로컬 수도권 역 목록(data/capital_stations.json)으로 출발역 자동완성을 제공합니다.

외부 API를 호출하지 않습니다. 계산에는 좌표(x, y)와 이름(place_name)만 쓰므로
카카오 검색 결과와 같은 모양의 역 정보를 만들어 돌려줍니다.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "data" / "capital_stations.json"
TOKEN_PREFIX = "local-"

# 원본은 공식 노선명입니다. 데이터에서 역 구성을 확인한 경우만 흔히 쓰는 이름을 덧붙입니다.
# 경원선은 1호선 역과 경의중앙선 역(이촌·한남 등)이 섞여 있어 한쪽으로 바꾸지 않습니다.
LINE_LABELS = {
    "경부선": "1호선 (경부선)",
    "경인선": "1호선 (경인선)",
    "경원선": "경원선 (1호선·경의중앙선)",
    "일산선": "3호선 (일산선)",
    "안산과천선": "4호선 (안산과천선)",
    "진접선": "4호선 (진접선)",
    "분당선": "수인분당선 (분당선)",
    "수인선": "수인분당선 (수인선)",
    "도시철도 7호선": "7호선",
    "수도권 광역철도 8호선": "8호선",
    "서울 도시철도 9호선": "9호선",
    "수도권  도시철도 9호선": "9호선",
    "수도권 경량도시철도 신림선": "신림선",
    "의정부": "의정부경전철",
    "에버라인": "용인경전철 (에버라인)",
    "인천국제공항선": "공항철도",
}


def base_name(name):
    """'용산역', '수원역(분당)'처럼 섞인 표기에서 끝의 '역'을 뗍니다."""
    return re.sub(r"역(?=\(|$)", "", name.strip())


def display_name(name):
    """'청량리(서울시립대입구)' → '청량리역(서울시립대입구)', '강남' → '강남역'."""
    if "(" in name:
        head, rest = name.split("(", 1)
        return f"{head}역({rest}"
    return f"{name}역"


def normalize(text):
    return re.sub(r"\s+", "", base_name(text)).lower()


@lru_cache(maxsize=1)
def load_catalog():
    stations = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog = []
    for index, station in enumerate(stations):
        name = base_name(station["place_name"])
        line = LINE_LABELS.get(station["line_name"], station["line_name"])
        display = display_name(name)
        catalog.append({
            "token": f"{TOKEN_PREFIX}{index}",
            "display": display,
            "line": line,
            "key": normalize(name),
            "station": {
                # 카카오 검색 결과와 같은 키를 사용해 기존 계산 코드를 그대로 씁니다.
                "place_name": f"{display} {line}",
                "address_name": "",
                "x": float(station["x"]),
                "y": float(station["y"]),
                "line_name": line,
            },
        })
    return catalog


def suggest(query, limit=6):
    """일치 → 앞부분 일치 → 포함 순으로 최대 limit개를 돌려줍니다."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 40:
        return []
    key = normalize(query)
    if not key:
        return []
    ranked = []
    for order, entry in enumerate(load_catalog()):
        if entry["key"] == key:
            rank = 0
        elif entry["key"].startswith(key):
            rank = 1
        elif key in entry["key"]:
            rank = 2
        else:
            continue
        ranked.append((rank, len(entry["key"]), entry["key"], order, entry))
    ranked.sort(key=lambda item: item[:4])
    return [{"token": e["token"], "name": e["display"], "line": e["line"]} for *_, e in ranked[:limit]]


def resolve(token):
    """local-번호 선택값을 역 정보로 바꿉니다. 형식이 맞지 않으면 None."""
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
        return None
    number = token[len(TOKEN_PREFIX):]
    catalog = load_catalog()
    if not number.isdigit() or int(number) >= len(catalog):
        return None
    return dict(catalog[int(number)]["station"])
