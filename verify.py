"""Verification harness — hits a running gym-tracker server and prints
acceptance-criteria results. Mirrors the curl commands in the README, but
uses urllib so it works without curl and across shells.

Usage:
    python3 verify.py                          # uses http://127.0.0.1:8080
    python3 verify.py http://localhost:8080    # explicit base URL
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8080"


def http(method: str, path: str, body=None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def section(name: str) -> None:
    print(f"\n===== {name} =====")


def expect(cond: bool, msg: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILED.append(msg)


FAILED: list[str] = []

# 1. Catalog
section("1. /api/exercises -> 200 with 26 entries")
s, t = http("GET", "/api/exercises")
d = json.loads(t)
expect(s == 200, f"HTTP 200 (got {s})")
expect(len(d) == 26, f"26 exercises (got {len(d)})")

# 2. Lineup
section("2. /api/categories/Chest-and-Biceps/lineup")
s, t = http("GET", "/api/categories/Chest-and-Biceps/lineup")
d = json.loads(t)
expect(s == 200 and len(d) == 5, f"5 exercises (got {len(d)})")
expect(d and d[0]["id"] == "barbell-bench-press", f"first = barbell-bench-press (got {d[0]['id'] if d else 'EMPTY'})")

# 3. Session lifecycle
section("3. Session create + add set + close + delete")
s, t = http("POST", "/api/sessions", {"category": "Chest-and-Biceps"})
expect(s == 201, f"create -> 201 (got {s})")
sess = json.loads(t)
SID = sess["id"]

s, t = http("POST", f"/api/sessions/{SID}/sets", {
    "exercise_id": "barbell-bench-press",
    "set_index": 1, "weight": 60, "reps": 10, "entry_status": "Completed",
})
expect(s == 201, f"add-set -> 201 (got {s})")

s, t = http("GET", f"/api/sessions/{SID}")
d = json.loads(t)
nested = sum(len(e.get("sets", [])) for e in d.get("exercises", []))
expect(s == 200 and nested == 1, f"session has 1 nested set (got {nested})")

s, t = http("PUT", f"/api/sessions/{SID}", {"end_time": "2026-01-01T12:00:00"})
expect(s == 200, f"close -> 200 (got {s})")

s, _ = http("DELETE", f"/api/sessions/{SID}")
expect(s == 204, f"delete -> 204 (got {s})")

# 4. Validation
section("4. Invalid category -> 422")
s, _ = http("POST", "/api/sessions", {"category": "Bogus"})
expect(s == 422, f"bad category -> 422 (got {s})")

# 5. Static pages
section("5. Static pages")
for path in ["/", "/exercises.html", "/logger.html", "/progress.html"]:
    s, _ = http("GET", path)
    expect(s == 200, f"GET {path} -> 200 (got {s})")

# 6. Dashboard shape
section("6. Dashboard payload shape")
s, t = http("GET", "/api/dashboard")
d = json.loads(t)
expected_keys = {
    "total_sessions", "total_volume_kg", "total_sets", "total_reps",
    "sessions_last_7_days", "sessions_last_30_days",
    "muscle_distribution", "recent_prs", "recent_sessions",
    "current_session", "weekly_volume",
}
expect(s == 200, f"GET /api/dashboard -> 200 (got {s})")
missing = expected_keys - set(d.keys())
expect(not missing, f"all expected keys present (missing: {missing})")

# 7. Health
section("7. Health")
s, t = http("GET", "/api/health")
expect(s == 200 and json.loads(t).get("status") == "ok", f"health ok (got {s} {t})")

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} checks")
    for f in FAILED:
        print(f"  - {f}")
    sys.exit(1)
print("ALL CHECKS PASSED")
