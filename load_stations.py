from pathlib import Path

from openpyxl import load_workbook

import json

BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "data" / "전체_도시철도역사정보_20260630.xlsx"

workbook = load_workbook(file_path, read_only=True, data_only=True)
sheet = workbook["표준데이터 역사"]

rows = sheet.iter_rows(values_only=True)
headers = next(rows)

print("열 이름:", headers)

# 수도권 역임을 확인
capital_stations = []
review_stations = []

for row in rows:
    station = dict(zip(headers, row))

    address = str(station["역사도로명주소"] or "").strip()
    operator = str(station["운영기관명"] or "").strip()
    line = str(station["노선명"] or "").strip()

    is_capital_address = address.startswith(("서울", "인천", "경기"))

    is_guri_line8 = (
            operator == "구리도시공사"
            and line == "8호선"
    )

    if is_capital_address or is_guri_line8:
        capital_stations.append(station)
    else:
        review_stations.append(station)

workbook.close()

prepared_stations = []

for station in capital_stations:
    prepared_station = {
        "place_name": station["역사명"],
        "station_code": str(station["역번호"]),
        "line_code": str(station["노선번호"]),
        "line_name": station["노선명"],
        "operator": station["운영기관명"],
        "x": float(station["역경도"]),
        "y": float(station["역위도"]),
    }

    prepared_stations.append(prepared_station)

output_path = BASE_DIR / "data" / "capital_stations.json"

output_path.write_text(
    json.dumps(
        prepared_stations,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ),
    encoding="utf-8",
)

print(f"역 정보 {len(prepared_stations)}개 저장 완료")
print("저장 위치:", output_path)

print("주소로 확인된 수도권 기록:", len(capital_stations))
print("추가 분류할 기록:", len(review_stations))

for station in capital_stations[:5]:
    print(
        station["역사명"],
        station["노선명"],
        station["역위도"],
        station["역경도"],
    )