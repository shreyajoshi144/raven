"""In-process HTTP metrics: per-minute buckets for the last two hours. Cheap enough to record on every request and exposed to
administrators (and, in Prometheus text form, to the monitoring stack). Each API process keeps its own counters; job, queue and
LLM statistics are read from PostgreSQL, so they are exact across processes."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from threading import Lock

KEEP_MINUTES = 120
_CAP = 600  # latency samples kept per minute bucket
_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_NUM = re.compile(r"/\d+(?=/|$)")
_SKIP = ("/static/", "/assets/", "/js/", "/css/", "/health/")


def route_label(path: str) -> str:
    return _NUM.sub("/{n}", _ID.sub("{id}", path))[:120]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(q * (len(v) - 1))))], 1)


class Metrics:
    def __init__(self) -> None:
        self.started = time.time()
        self._lock = Lock()
        self._b: dict[int, dict] = {}
        self._routes: dict[str, dict] = defaultdict(lambda: {"n": 0, "e5": 0, "sum": 0.0, "max": 0.0})
        self.total = {"n": 0, "e4": 0, "e5": 0}

    def record(self, path: str, status: int, ms: float, now: float | None = None) -> None:
        if path.startswith(_SKIP):
            return
        minute = int((now or time.time()) // 60)
        with self._lock:
            b = self._b.setdefault(minute, {"n": 0, "e4": 0, "e5": 0, "lat": []})
            b["n"] += 1
            self.total["n"] += 1
            if status >= 500:
                b["e5"] += 1; self.total["e5"] += 1
            elif status >= 400:
                b["e4"] += 1; self.total["e4"] += 1
            if len(b["lat"]) < _CAP:
                b["lat"].append(ms)
            r = self._routes[route_label(path)]
            r["n"] += 1; r["sum"] += ms; r["max"] = max(r["max"], ms); r["e5"] += 1 if status >= 500 else 0
            for old in [m for m in self._b if m < minute - KEEP_MINUTES]:
                del self._b[old]
            if len(self._routes) > 500:  # bound label cardinality
                for k in sorted(self._routes, key=lambda k: self._routes[k]["n"])[:100]:
                    del self._routes[k]

    def snapshot(self, minutes: int = 60, now: float | None = None) -> dict:
        end = int((now or time.time()) // 60)
        with self._lock:
            series, allat, n, e4, e5 = [], [], 0, 0, 0
            for m in range(end - minutes + 1, end + 1):
                b = self._b.get(m)
                series.append({"t": m * 60, "n": b["n"] if b else 0, "e4": b["e4"] if b else 0, "e5": b["e5"] if b else 0, "p95_ms": percentile(b["lat"], .95) if b else None})
                if b:
                    allat += b["lat"]; n += b["n"]; e4 += b["e4"]; e5 += b["e5"]
            routes = sorted(({"route": k, "n": v["n"], "avg_ms": round(v["sum"] / v["n"], 1), "max_ms": round(v["max"], 1), "errors_5xx": v["e5"]} for k, v in self._routes.items() if v["n"]),
                            key=lambda r: -r["avg_ms"] * min(r["n"], 20))[:8]
            return {"window_minutes": minutes, "series": series, "requests": n, "errors_4xx": e4, "errors_5xx": e5, "p50_ms": percentile(allat, .5), "p95_ms": percentile(allat, .95),
                    "p99_ms": percentile(allat, .99), "error_rate": round(e5 / n, 4) if n else 0.0, "slowest_routes": routes, "uptime_seconds": int(time.time() - self.started),
                    "scope": "this API process"}

    def reset(self) -> None:
        with self._lock:
            self._b.clear(); self._routes.clear(); self.total.update(n=0, e4=0, e5=0)


metrics = Metrics()
