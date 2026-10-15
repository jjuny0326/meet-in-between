import unittest

import station_catalog as catalog


class StationCatalogTests(unittest.TestCase):
    def test_exact_then_prefix_then_contains(self):
        names = [item["name"] for item in catalog.suggest("강남")]
        self.assertEqual(names[:2], ["강남역", "강남역"])
        self.assertIn("강남구청역", names)
        self.assertLess(names.index("강남대역"), names.index("강남구청역"))

    def test_same_name_lists_seoul_subway_lines_first(self):
        # 대부분의 사용자가 떠올리는 노선(1~9호선)을 먼저 보여줍니다.
        self.assertEqual([item["line"] for item in catalog.suggest("강남")[:2]], ["2호선", "신분당선"])
        self.assertEqual(catalog.line_order("1호선 (경부선)"), (0, 1))
        self.assertEqual(catalog.line_order("신분당선"), (1, 0))

    def test_mixed_station_suffix_is_normalized(self):
        # 원본에 '용산역'처럼 '역'이 붙은 이름과 '강남'처럼 없는 이름이 섞여 있습니다.
        self.assertEqual(catalog.suggest("용산역")[0]["name"], "용산역")
        self.assertEqual(catalog.suggest("용산")[0]["name"], "용산역")
        self.assertEqual(catalog.base_name("수원역(분당)"), "수원(분당)")
        self.assertEqual(catalog.display_name("청량리(서울시립대입구)"), "청량리역(서울시립대입구)")

    def test_line_labels_only_where_data_confirms(self):
        lines = {item["line"] for item in catalog.suggest("부평")}
        self.assertIn("1호선 (경인선)", lines)
        self.assertIn("경원선 (1호선·경의중앙선)", {item["line"] for item in catalog.suggest("청량리")})

    def test_invalid_queries_and_tokens(self):
        for query in ("", "   ", None, "가" * 41):
            self.assertEqual(catalog.suggest(query), [])
        for token in (None, "x", "local-", "local--1", "local-1.5", "local-999999"):
            self.assertIsNone(catalog.resolve(token))

    def test_resolved_station_matches_calculation_shape(self):
        token = catalog.suggest("강남")[1]["token"]
        station = catalog.resolve(token)
        self.assertEqual(set(station), {"place_name", "address_name", "x", "y", "line_name"})
        self.assertTrue(-180 <= station["x"] <= 180 and -90 <= station["y"] <= 90)
        # 호출자가 바꿔도 목록 원본은 변하지 않습니다.
        station["x"] = 0
        self.assertNotEqual(catalog.resolve(token)["x"], 0)


if __name__ == "__main__":
    unittest.main()
