"""What each applied suggestion did: the record that closes the improvement loop.

Every suggestion the user applied or dismissed stays in the `suggestions` collection. For an applied one, code
compares the posts scored before it with the posts scored after it, using the user's own verdicts:

- A Profile change (weights, a rubric, roles, keywords, industries, titles to skip) is measured on the search's
  judged posts, split by the profile version that scored them. Weights and rubrics aim to order posts better, so
  they are read by agreement; the others aim to bring in better posts, so they are read by the share marked Good.
- An added board is measured by the posts it brought to the model since it was added, and your verdicts on them.
- A board turned off has nothing left to measure.

The page computes the same numbers (console.html, changeOutcome) to show them; `suggest prepare` hands them to the
model as `track_record`, and code uses them to propose undoing a change that hurt and to skip what was dismissed.
Counts are small, so every result carries its counts, and nothing is called better or worse on fewer than
MIN_JUDGED posts judged since.
"""

from datetime import datetime

MIN_JUDGED = 3      # posts judged since the change before it is read at all
CLEAR = 10          # points of change in agreement or share Good before it counts as helped or hurt


def ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def agreement(rows):
    g = [m["total"] for m, v in rows if v == "accept"]
    n = [m["total"] for m, v in rows if v == "dismiss"]
    if not g or not n:
        return None
    w = sum(1 if a > b else .5 if a == b else 0 for a in g for b in n)
    return round(100 * w / (len(g) * len(n)))


def good_share(rows):
    return round(100 * sum(1 for _, v in rows if v == "accept") / len(rows)) if rows else None


def counts(rows):
    return {"judged": len(rows), "good": sum(1 for _, v in rows if v == "accept"), "nope": sum(1 for _, v in rows if v == "dismiss")}


def sources_of(m):
    return m.get("sources") or [m.get("posting_id", "").rsplit(":", 1)[0]]


def outcome(it, matches, judgments, runs):
    """{verdict, text, ...numbers} for one applied suggestion item. verdict: waiting, too_early, helped,
    no_change, hurt, nothing (a board that brought no posts to the model), only_nope, na."""
    at = ts(it.get("applied_at"))
    n_runs = sum(1 for r in runs.values() if r.get("status") == "ok" and ts(r.get("started")) > at)
    out = {"runs_since": n_runs}
    if it["target"] == "sources_off":
        return {**out, "verdict": "na", "text": "Not read since, so there is nothing to measure."}
    if n_runs == 0:
        return {**out, "verdict": "waiting", "text": "No run since it was applied."}
    verdict = lambda mid: (judgments.get(mid) or {}).get("verdict")
    if it["target"] == "sources_add":
        sid = it["proposed"]["id"]
        mine = [m for mid, m in matches.items() if sid in sources_of(m) and ts(m.get("first_seen_at")) > at]
        rows = [(m, verdict(m["id"])) for m in mine if verdict(m["id"]) in ("accept", "dismiss")]
        c = {**counts(rows), "scored": len(mine)}
        if c["good"]:
            return {**out, **c, "verdict": "helped", "text": f"{c['good']} Good of {c['scored']} posts it brought to the model."}
        if not mine and n_runs >= 3:
            return {**out, **c, "verdict": "nothing", "text": f"No post from it reached the model in {n_runs} runs."}
        if c["judged"] >= MIN_JUDGED:
            return {**out, **c, "verdict": "only_nope", "text": f"All {c['judged']} posts you judged from it were Nope."}
        return {**out, **c, "verdict": "too_early", "text": f"{c['scored']} posts from it reached the model; {c['judged']} judged so far."}
    v = it.get("applied_version") or 0
    rows = [(m, verdict(mid)) for mid, m in matches.items()
            if m.get("search_id") == it.get("search_id") and verdict(mid) in ("accept", "dismiss")]
    before = [(m, x) for m, x in rows if (m.get("prefs_version") or 0) < v]
    after = [(m, x) for m, x in rows if (m.get("prefs_version") or 0) >= v]
    by_order = it["target"] == "weights" or it["target"].startswith("rubric:")
    measure, name = (agreement, "agreement") if by_order else (good_share, "share marked Good")
    b, a = measure(before), measure(after)
    c = {"metric": name, "before": b, "after": a, "judged_before": len(before), **counts(after)}
    if b is None:
        return {**out, **c, "verdict": "too_early", "text": f"No posts judged before it to compare with; {len(after)} judged since."}
    if len(after) < MIN_JUDGED or a is None:
        return {**out, **c, "verdict": "too_early", "text": f"{len(after)} posts judged since; it needs {MIN_JUDGED} or more"
                + (", with Good and Nope among them" if by_order else "") + "."}
    d = a - b
    kind = "helped" if d >= CLEAR else "hurt" if d <= -CLEAR else "no_change"
    return {**out, **c, "verdict": kind, "text": f"{name.capitalize()} {b}% before, {a}% after, on {len(before)} and {len(after)} judged posts."}


def record(suggestions, matches, judgments, runs, limit=30):
    """Every applied or dismissed suggestion, newest first, with its outcome when applied."""
    rows = []
    for doc in suggestions.values():
        for it in doc.get("items", []):
            if it.get("status") not in ("applied", "dismissed"):
                continue
            r = {k: it.get(k) for k in ("target", "label", "search_id", "status", "applied_at", "applied_version", "current", "proposed", "why")}
            r["at"] = it.get("applied_at") or doc.get("at")
            if it["status"] == "applied":
                r["outcome"] = outcome(it, matches, judgments, runs)
            rows.append(r)
    rows.sort(key=lambda r: ts(r["at"]), reverse=True)
    return rows[:limit]
