import unittest
from unittest.mock import patch

import station_search as app
import recommendation_policy as policy


def candidate(name, a, b, transfers):
    return {"station": {"place_name": name, "line_name": "테스트"}, "minutes_a": a, "minutes_b": b,
            "longest": max(a, b), "total": a+b, "difference": abs(a-b),
            "transfers_a": transfers, "transfers_b": 0}


def route(minutes, transfers):
    return {"properties": {"totalTime": minutes*60, "transfers": transfers}}


class RecommendationPolicyTests(unittest.TestCase):
    def test_three_modes_select_different_candidates_before_top_three(self):
        rows = [candidate("빠른역", 20, 40, 4), candidate("공평역", 45, 45, 2),
                candidate("환승역", 40, 50, 0), candidate("가까운역", 25, 41, 3),
                candidate("너무먼역", 90, 90, 1)]
        actual = {mode:[r["station"]["place_name"] for r in policy.rank_candidates(rows, mode)[:3]] for mode in policy.MODES}
        self.assertEqual(actual["burden"], ["빠른역", "가까운역", "공평역"])
        self.assertEqual(actual["fair"], ["공평역", "환승역", "가까운역"])
        self.assertEqual(actual["transfers"], ["환승역", "너무먼역", "공평역"])
        self.assertEqual(rows[0]["station"]["place_name"], "빠른역")

    def test_fair_boundary_and_fewer_than_three_are_honored(self):
        best = candidate("best", 20, 40, 0)
        boundary = candidate("edge", 55, 55, 0)
        outside = candidate("out", 55.01, 55.01, 0)
        self.assertEqual([r["station"]["place_name"] for r in policy.rank_candidates([best,boundary,outside], "fair")], ["edge","best"])
        self.assertEqual(policy.rank_candidates([], "fair"), [])

    def test_transfer_mode_selects_less_transfer_route_not_fastest(self):
        routes = [route(30,2),route(45,0),route(50,0)]
        self.assertEqual(policy.select_route(routes,"burden"), routes[0])
        self.assertEqual(policy.select_route(routes,"fair"), routes[0])
        self.assertEqual(policy.select_route(routes,"transfers"), routes[1])

    def test_invalid_mode_stops_before_any_lookup(self):
        with patch.object(app, "find_meeting_candidates") as find:
            with self.assertRaises(ValueError):
                app.build_recommendation({}, {}, [], "dummy", mode="invalid")
            find.assert_not_called()

    def test_build_uses_selected_routes_and_saves_policy_for_analysis(self):
        with patch.object(app,"find_meeting_candidates",return_value=[{"place_name":"후보","line_name":"1"}]), \
                patch.object(app,"ensure_route_capacity"), \
                patch.object(app,"get_transit_routes",return_value=[route(30,2),route(45,0)]) as paths, \
                patch.object(app,"enrich_recommendations",side_effect=lambda rows,*args:[{**r,"rank":i+1} for i,r in enumerate(rows[:3])]), \
                patch.object(app,"analyze_recommendations",return_value={}) as analyze:
            report = app.build_recommendation({"place_name":"A"},{"place_name":"B"},["cafe"],"dummy",mode="transfers")
            self.assertEqual(report["recommendation_mode"], "transfers")
            self.assertEqual(report["recommendations"][0]["minutes_a"],45)
            self.assertEqual(report["recommendations"][0]["transfers_a"],0)
            self.assertEqual(paths.call_count,2)
            self.assertEqual(analyze.call_args.args[2],"transfers")
