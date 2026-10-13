"""추천 기준에 따른 경로 선택과 후보 순위. 외부 API 호출은 하지 않습니다."""

MODES = {
    "burden": "이동 부담 줄이기",
    "fair": "공평하게 만나기",
    "transfers": "환승 적게 하기",
}
FAIR_EXTRA_MINUTES = 15


def validate_mode(mode):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("지원하지 않는 추천 기준입니다.")
    return mode


def mode_description(mode):
    validate_mode(mode)
    return {
        "burden": "각자의 최단시간 경로로 비교해 더 오래 걸리는 사람의 시간을 먼저 줄입니다. 동률이면 두 사람의 시간 합계를 비교합니다.",
        "fair": f"각자의 최단시간 경로로 비교합니다. 더 오래 걸리는 시간이 가장 짧은 후보보다 {FAIR_EXTRA_MINUTES}분 이내로 더 걸리는 후보만 남기고, 두 사람의 시간 차이 순으로 고릅니다.",
        "transfers": "각자 환승이 가장 적은 경로를 고른 뒤 두 사람의 환승 합계 순으로 비교합니다. 동률이면 더 긴 이동시간, 시간 합계 순으로 고릅니다. 이동시간은 늘어날 수 있습니다.",
    }[mode]


def select_route(routes, mode):
    validate_mode(mode)
    def key(route):
        value = route["properties"]
        if mode == "transfers":
            return value["transfers"], value["totalTime"]
        return value["totalTime"], value["transfers"]
    return min(routes, key=key)


def rank_candidates(results, mode):
    validate_mode(mode)
    eligible = list(results)
    if mode == "fair" and eligible:
        ceiling = min(item["longest"] for item in eligible) + FAIR_EXTRA_MINUTES
        eligible = [item for item in eligible if item["longest"] <= ceiling]
    def key(item):
        common = (item["longest"], item["total"])
        if mode == "fair":
            return (item["difference"], *common)
        if mode == "transfers":
            return (item["transfers_a"] + item["transfers_b"], *common)
        return common
    return sorted(eligible, key=key)
