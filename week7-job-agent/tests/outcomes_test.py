"""What an applied suggestion did, on made-up data: uv run python tests/outcomes_test.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobagent import outcomes  # noqa: E402

T0, T1, T2 = "2026-10-01T09:00:00+00:00", "2026-10-05T09:00:00+00:00", "2026-10-09T09:00:00+00:00"


def match(i, total, version, src="greenhouse:acme", seen=T0):
    return {"id": f"m{i}", "search_id": "s", "total": total, "prefs_version": version, "sources": [src], "first_seen_at": seen}


# Before the change (profile v1): Good posts score high, Nope low. After it (v2): the order flips.
ms = [match(1, 80, 1), match(2, 75, 1), match(3, 30, 1), match(4, 25, 1),
      match(5, 30, 2, seen=T2), match(6, 35, 2, seen=T2), match(7, 80, 2, seen=T2), match(8, 70, 2, seen=T2),
      match(9, 60, 2, "greenhouse:newco", T2), match(10, 55, 2, "lever:other", T2), match(11, 50, 2, "lever:other", T2), match(12, 45, 2, "lever:other", T2)]
matches = {m["id"]: m for m in ms}
v = {"m1": "accept", "m2": "accept", "m3": "dismiss", "m4": "dismiss",
     "m5": "accept", "m6": "accept", "m7": "dismiss", "m8": "dismiss",
     "m9": "accept", "m10": "dismiss", "m11": "dismiss", "m12": "dismiss"}
judgments = {k: {"verdict": x} for k, x in v.items()}
runs = {"r1": {"status": "ok", "started": T2}}

weights = {"target": "weights", "search_id": "s", "applied_version": 2, "applied_at": T1}
o = outcomes.outcome(weights, matches, judgments, runs)
assert o["verdict"] == "hurt" and o["before"] == 100 and o["after"] < 50, o

roles = {"target": "target_roles", "search_id": "s", "applied_version": 2, "applied_at": T1}
o = outcomes.outcome(roles, matches, judgments, runs)
assert o["metric"] == "share marked Good" and o["before"] == 50, o

newco = {"target": "sources_add", "proposed": {"id": "greenhouse:newco"}, "applied_at": T1}
assert outcomes.outcome(newco, matches, judgments, runs)["verdict"] == "helped"

other = {"target": "sources_add", "proposed": {"id": "lever:other"}, "applied_at": T1}
assert outcomes.outcome(other, matches, judgments, runs)["verdict"] == "only_nope"

late = {**weights, "applied_at": "2026-10-10T00:00:00+00:00"}
assert outcomes.outcome(late, matches, judgments, runs)["verdict"] == "waiting"

few = {k: x for k, x in judgments.items() if k in ("m1", "m2", "m3", "m4", "m5", "m8")}
assert outcomes.outcome(weights, matches, few, runs)["verdict"] == "too_early"

off = {"target": "sources_off", "proposed": ["x"], "applied_at": T1}
assert outcomes.outcome(off, matches, judgments, runs)["verdict"] == "na"

print("outcomes: 7 cases pass")
