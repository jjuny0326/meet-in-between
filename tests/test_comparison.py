import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import comparison as c
import station_search as app


def result(number=1):
    return {
        "station": {"place_name": f"후보{number}역", "line_name": "1호선", "x": 127, "y": 37},
        "minutes_a": 40 + number, "minutes_b": 42 + number,
        "transfers_a": 1, "transfers_b": 2,
        "total": 82 + 2 * number, "difference": 2, "longest": 42 + number,
    }


def recommendations():
    with patch.object(c, "search_nearby_places", return_value=[]):
        return c.enrich_recommendations([result(i) for i in range(1, 4)], ["cafe"], "dummy")


def place(number, address, name=None):
    return {"id": str(number), "place_name": name or f"카페{number}",
            "road_address_name": address, "address_name": "", "distance": str(number * 10)}


def report():
    items = recommendations()
    return {
        "schema_version": 1, "collected_at": "2026-10-07T12:00:00+09:00",
        "preferences": ["cafe"], "recommendations": items,
        "analysis": c.basic_analysis(items, ["cafe"], "테스트"),
    }


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        # 모든 테스트에서 네트워크를 막고 키와 사용량/저장 파일을 격리합니다.
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.base = Path(directory)
        self.stack.enter_context(patch.object(c, "BASE_DIR", self.base))
        self.stack.enter_context(patch.object(c, "REPORT_PATH", self.base / "report.json"))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(app, "load_dotenv"))
        self.get = self.stack.enter_context(patch.object(requests, "get", side_effect=AssertionError("Unexpected GET")))
        self.post = self.stack.enter_context(patch.object(requests, "post", side_effect=AssertionError("Unexpected POST")))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def enable_ai(self):
        os.environ.update(GEMINI_API_KEY="dummy-secret", GEMINI_FREE_TIER_CONFIRMED="true")

    def ai_response(self, data):
        self.post.side_effect = None
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(data)}]},
        }]}

    def test_preferences_default_multiple_and_invalid(self):
        self.assertEqual(c.parse_preferences(""), ["cafe"])
        self.assertEqual(c.parse_preferences("3,1,3 2"), ["culture", "cafe", "food"])
        for value in (",,", "4", "1,cafe"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.parse_preferences(value)

    def test_only_selected_categories_and_three_candidates(self):
        with patch.object(c, "search_nearby_places", return_value=[]) as search:
            items = c.enrich_recommendations([result(i) for i in range(5)], ["food", "culture"], "dummy")
        self.assertEqual(len(items), 3)
        self.assertEqual(search.call_count, 6)
        self.assertEqual(set(items[0]["places"]), {"food", "culture"})

    def test_category_query_uses_radius_and_normalizes_fields(self):
        self.get.side_effect = None
        self.get.return_value = Mock(status_code=200)
        self.get.return_value.json.return_value = {"documents": [{
            "id": "123", "place_name": "식당", "road_address_name": "",
            "address_name": "지번 주소", "distance": "100",
        }]}
        items = c.search_nearby_places(result()["station"], "food", "dummy")
        self.assertEqual(items[0]["address"], "지번 주소")
        self.assertEqual(self.get.call_args.kwargs["params"]["category_group_code"], "FD6")
        self.assertEqual(self.get.call_args.kwargs["params"]["radius"], 1000)
        self.assertEqual(self.get.call_args.kwargs["params"]["size"], 15)
        self.get.assert_called_once()

    def test_different_buildings_are_selected_before_second_shop(self):
        documents = [place(i, "서울 금천구 가산디지털1로 168") for i in range(1, 7)]
        documents += [place(i, f"서울 금천구 가산디지털1로 {168 + i}") for i in range(7, 11)]
        selected = c.select_diverse_places(documents)
        self.assertEqual([p["id"] for p in selected], ["1", "7", "8", "9", "10"])

    def test_same_building_cap_even_when_not_enough_alternatives(self):
        documents = [place(i, "서울 구로구 경인로 430") for i in range(1, 8)]
        documents.append(place(8, "서울 구로구 구일로 130"))
        self.assertEqual([p["id"] for p in c.select_diverse_places(documents)], ["1", "2", "8"])

    def test_floors_are_grouped_but_building_subnumbers_are_preserved(self):
        documents = [place(1, "서울 금천구 범안로 1142 1층"),
                     place(2, "서울  금천구 범안로 1142, 201호"),
                     place(3, "서울 금천구 범안로 1142-1")]
        self.assertEqual(c.building_key(documents[0]), c.building_key(documents[1]))
        self.assertNotEqual(c.building_key(documents[0]), c.building_key(documents[2]))

    def test_missing_addresses_stay_separate_and_duplicate_ids_are_removed(self):
        documents = [place(i, "") for i in range(1, 6)]
        documents.insert(1, documents[0])
        self.assertEqual(len(c.select_diverse_places(documents)), 5)
        jibeon = place(9, "")
        jibeon["address_name"] = "서울 구로구 고척동 63-6"
        self.assertEqual(c.building_key(jibeon), "lot:서울 구로구 고척동 63-6")

    def test_access_clues_and_indirect_same_address_warning(self):
        documents = [place(1, "서울 구로구 경인로 430", "매머드커피 2호점"),
                     place(2, "서울 구로구 구일로 130", "동네카페"),
                     place(3, "서울 구로구 경인로 430", "스트릿츄러스 3층외야")]
        selected = c.select_diverse_places(documents)
        self.assertTrue(selected[0]["access_check_required"])
        self.assertIn("같은 주소", selected[0]["access_check_reasons"][0])
        self.assertFalse(selected[1]["access_check_required"])
        self.assertIn("관람권", selected[2]["access_check_reasons"][0])
        for name in ("카페 2층1루", "출국장 카페", "회원 전용 식당"):
            self.assertTrue(c.access_check_reasons(name), name)
        for name in ("카페 2층", "메가커피 독산역점", "루프탑카페"):
            self.assertEqual(c.access_check_reasons(name), [], name)

    def test_access_notes_reach_saved_report_console_and_ai(self):
        saved = report()
        items = c.select_diverse_places([place(1, "서울 구로구 경인로 430", "카페 2층1루")])
        saved["recommendations"][0]["places"]["cafe"]["items"] = items
        saved["analysis"] = c.basic_analysis(saved["recommendations"], ["cafe"], "테스트")
        self.assertIn("출입 조건", saved["analysis"]["comparisons"][0]["limitations"][0])
        c.save_report(saved)
        output = io.StringIO()
        with redirect_stdout(output):
            app.main(["--saved"])
        self.assertIn("[출입 조건 확인 필요]", output.getvalue())
        self.assertEqual(c.load_report(), saved)
        self.enable_ai()
        self.ai_response({**saved["analysis"], "recommended_rank": 1})
        c.analyze_recommendations(saved["recommendations"], ["cafe"])
        payload = self.post.call_args.kwargs["json"]
        evidence = json.loads(payload["contents"][0]["parts"][0]["text"])["evidence"]
        self.assertTrue(evidence[0]["places"]["cafe"]["items"][0]["access_check_required"])
        self.assertNotIn("서울 구로구 경인로 430", json.dumps(payload, ensure_ascii=False))

    def test_search_failure_does_not_hide_other_candidates(self):
        with patch.object(c, "search_nearby_places", side_effect=[RuntimeError("조회 실패"), [], []]):
            items = c.enrich_recommendations([result(i) for i in range(3)], ["cafe"], "dummy")
        analysis = c.basic_analysis(items, ["cafe"], "테스트")
        self.assertIn("실패", analysis["comparisons"][0]["limitations"][0])
        self.assertIn("찾지 못", analysis["comparisons"][1]["limitations"][0])

    def test_ai_requires_both_key_and_free_tier_confirmation(self):
        for env in ({}, {"GEMINI_API_KEY": "dummy"}, {"GEMINI_FREE_TIER_CONFIRMED": "true"}):
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(c.analyze_recommendations(recommendations(), ["cafe"])["source"], "rules")
        self.post.assert_not_called()
        self.assertFalse((self.base / ".ai_usage.json").exists())

    def test_ai_success_preserves_all_candidates_and_omits_precise_locations(self):
        self.enable_ai()
        data = {"summary": "세 후보 중 2번을 추천합니다.", "recommended_rank": 2,
                "comparisons": [{"rank": i, "strengths": ["비교 장점"], "limitations": ["정보 부족"]} for i in (3, 1, 2)]}
        self.ai_response(data)
        actual = c.analyze_recommendations(recommendations(), ["cafe"])
        self.assertEqual(actual["source"], "gemini")
        self.assertEqual(actual["recommended_rank"], 2)
        self.assertEqual([i["rank"] for i in actual["comparisons"]], [1, 2, 3])
        payload = self.post.call_args.kwargs["json"]
        evidence = json.loads(payload["contents"][0]["parts"][0]["text"])["evidence"]
        self.assertNotIn("x", evidence[0])
        self.assertNotIn("address", evidence[0])
        self.assertNotIn("dummy-secret", json.dumps(payload))
        self.post.assert_called_once()

    def test_unknown_or_duplicate_ai_rank_is_rejected(self):
        data = {"summary": "요약", "recommended_rank": 1,
                "comparisons": [{"rank": i, "strengths": ["장점"], "limitations": ["한계"]} for i in (1, 2, 3)]}
        for ranks, recommended in (([1, 1, 3], 1), ([1, 2, 3], 4)):
            invalid = copy.deepcopy(data)
            invalid["recommended_rank"] = recommended
            for item, rank in zip(invalid["comparisons"], ranks):
                item["rank"] = rank
            with self.assertRaises(ValueError):
                c.validate_analysis(invalid, [1, 2, 3])

    def test_invalid_ai_output_falls_back(self):
        self.enable_ai()
        self.ai_response({"recommended_rank": 99})
        actual = c.analyze_recommendations(recommendations(), ["cafe"])
        self.assertEqual(actual["source"], "rules")
        self.assertEqual(len(actual["comparisons"]), 3)

    def test_http_limit_falls_back_without_retry_and_counts_attempt(self):
        self.enable_ai()
        self.post.side_effect = None
        self.post.return_value = Mock(status_code=429)
        actual = c.analyze_recommendations(recommendations(), ["cafe"])
        self.assertEqual(actual["source"], "rules")
        self.assertIn("429", actual["status"])
        self.post.assert_called_once()
        self.assertEqual(json.loads((self.base / ".ai_usage.json").read_text())["count"], 1)

    def test_ai_interval_and_daily_limit_block_network(self):
        self.enable_ai()
        now = datetime.now(c.KOREA_TIME)
        path = self.base / ".ai_usage.json"
        for count, last in ((10, 0), (1, now.timestamp())):
            path.write_text(json.dumps({"date": now.date().isoformat(), "count": count, "last_request": last}))
            self.assertEqual(c.analyze_recommendations(recommendations(), ["cafe"])["source"], "rules")
        self.post.assert_not_called()

    def test_ai_usage_resets_next_day_but_corrupt_record_is_not_reset(self):
        path = self.base / ".ai_usage.json"
        yesterday = datetime.now(c.KOREA_TIME) - timedelta(days=1)
        path.write_text(json.dumps({"date": yesterday.date().isoformat(), "count": 10, "last_request": yesterday.timestamp()}))
        c.reserve_ai_call()
        self.assertEqual(json.loads(path.read_text())["count"], 1)
        path.write_text("broken")
        with self.assertRaises(RuntimeError):
            c.reserve_ai_call()
        self.assertEqual(path.read_text(), "broken")

    def test_saved_mode_needs_no_key_and_no_api(self):
        expected = report()
        c.save_report(expected)
        self.assertEqual(app.main(["--saved"]), expected)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_missing_saved_report_does_not_start_live_search(self):
        with self.assertRaises(SystemExit):
            app.main(["--saved"])
        self.get.assert_not_called()

    def test_explain_saved_only_calls_ai_and_keeps_evidence(self):
        self.enable_ai()
        saved = report()
        c.save_report(saved)
        self.ai_response({**saved["analysis"], "recommended_rank": 2})
        actual = app.main(["--explain-saved"])
        self.assertEqual(actual["recommendations"], saved["recommendations"])
        self.assertEqual(actual["collected_at"], saved["collected_at"])
        self.assertEqual(actual["analysis"]["source"], "gemini")
        self.get.assert_not_called()
        self.post.assert_called_once()

    def test_main_ranks_routes_then_enriches_three_and_saves(self):
        os.environ["KAKAO_REST_API_KEY"] = "dummy"
        candidates = [result(i)["station"] for i in range(5)]
        routes = [[{"properties": {"totalTime": minutes * 60, "transfers": 1}}]
                  for minutes in (60, 60, 40, 42, 45, 43, 70, 72, 90, 95)]
        with patch.object(app, "select_preferences", return_value=["cafe", "culture"]), \
                patch.object(app, "select_station", return_value=candidates[0]), \
                patch.object(app, "find_meeting_candidates", return_value=candidates), \
                patch.object(app, "get_transit_routes", side_effect=routes) as transit, \
                patch.object(c, "search_nearby_places", return_value=[]) as places:
            actual = app.main([])
        self.assertEqual(transit.call_count, 10)
        self.assertEqual(places.call_count, 6)
        self.assertEqual([item["station"]["place_name"] for item in actual["recommendations"]], ["후보1역", "후보2역", "후보0역"])
        self.assertEqual(c.load_report(), actual)
        self.assertNotIn("dummy", c.REPORT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
