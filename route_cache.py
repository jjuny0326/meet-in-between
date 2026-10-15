"""성공한 전체 경로 목록을 잠시 보관하는 프로세스 내부 캐시."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
from threading import RLock
import time

KOREA_TIME = timezone(timedelta(hours=9))


class RouteCache:
    def __init__(self, ttl_seconds=600, max_entries=200, clock=None, timestamp=None):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock or time.monotonic
        self.timestamp = timestamp or (lambda: datetime.now(KOREA_TIME).isoformat())
        self.entries = OrderedDict()
        self.lock = RLock()

    @staticmethod
    def key(start, end, api_key):
        values = []
        for station in (start, end):
            for field, limit in (("x", 180), ("y", 90)):
                raw = station[field]
                if isinstance(raw, bool):
                    raise ValueError("잘못된 경로 좌표")
                value = float(raw)
                if not isfinite(value) or abs(value) > limit:
                    raise ValueError("잘못된 경로 좌표")
                values.append(value)
        # 방향을 유지하고 다른 API 키의 결과는 섞지 않습니다. 키 원문은 보관하지 않습니다.
        return (sha256(api_key.encode()).hexdigest(), *values)

    def load_batch(self, pairs, api_key, fetch, check_capacity):
        """요청 시작 시 유효한 캐시를 확보하고, 없는 구간만 한도 검사 후 조회합니다."""
        with self.lock:
            now = self.clock()
            for key, entry in list(self.entries.items()):
                if now - entry["stored_at"] >= self.ttl_seconds:
                    del self.entries[key]
            keys = [self.key(start, end, api_key) for start, end in pairs]
            available = {key: deepcopy(self.entries[key]) for key in keys if key in self.entries}
            missing = dict.fromkeys(key for key in keys if key not in available)
            if missing:
                check_capacity(len(missing))
            output = []
            api_calls = 0
            for key, (start, end) in zip(keys, pairs):
                cached = key in available
                if not cached:
                    # fetch가 응답을 검증한 뒤 반환합니다. 실패하면 저장하지 않습니다.
                    routes = fetch(start, end, api_key)
                    entry = {"routes": deepcopy(routes), "fetched_at": self.timestamp(), "stored_at": self.clock()}
                    self.entries[key] = entry
                    available[key] = entry
                    api_calls += 1
                    while len(self.entries) > self.max_entries:
                        self.entries.popitem(last=False)
                entry = available[key]
                output.append({"routes": deepcopy(entry["routes"]), "fetched_at": entry["fetched_at"], "source": "cache" if cached else "api"})
            dates = [entry["fetched_at"] for entry in output]
            return output, {
                "cache_hits": len(output) - api_calls, "api_calls": api_calls,
                "oldest_fetched_at": min(dates) if dates else None,
                "latest_fetched_at": max(dates) if dates else None,
                "ttl_seconds": self.ttl_seconds,
            }
