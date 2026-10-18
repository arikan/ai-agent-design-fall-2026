"""Job agent engine, minimal version. Python standard library only.

The engine is the deterministic shell around the agent. It never calls a model.
Claude (the scheduled session) does the judging between the two commands:

  uv run engine.py prepare  config.json   -> work/batch.json   (what Claude must judge)
  uv run engine.py finish   config.json   -> work/results.json (matches, run record, trace)

Everything the engine decides is written to the trace, so a run can be read step by step.
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
WORK = HERE / "work"
CAPS = json.loads((HERE / "caps.json").read_text())

REQUIRED_FIELDS = ["company", "title", "location", "text"]
SCORES = {1, 2, 3, 4, 5}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_jsonl(path):
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def step(trace, name, **fields):
    entry = {"step": name, "at": now(), **fields}
    trace.append(entry)
    return entry


# ---------------------------------------------------------------- prepare

def load_sources(agent, trace):
    """Collect postings from every enabled source. Fetching sources were already
    run by sources.py; their postings and health wait in work/. The engine checks
    each posting again rather than trusting the adapter."""
    fetched_health = {}
    fh = WORK / "fetch_health.json"
    if fh.exists():
        fetched_health = {h["source"]: h for h in json.loads(fh.read_text())}
    postings, health = [], []
    for src in agent["sources"]:
        if not src.get("enabled"):
            continue
        sid = src["id"]
        if src["adapter"] == "manual":
            health.append({"source": sid, "status": "manual", "note": src.get("note", "")})
            continue
        if src["adapter"] == "corpus":
            path, h = HERE / "corpus" / "postings.jsonl", {"source": sid, "status": "ok"}
        else:
            path = WORK / "fetched" / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', sid)}.jsonl"
            h = dict(fetched_health.get(sid) or {"source": sid, "status": "failed", "error": "not fetched this run"})
            h.pop("requests", None)
        rows = load_jsonl(path) if path.exists() else []
        valid = []
        for r in rows:
            if all(str(r.get(f) or "").strip() for f in REQUIRED_FIELDS):
                r["source"] = sid
                if src.get("category") and not r.get("category"):
                    r["category"] = src["category"]
                valid.append(r)
        cap = min(int(src.get("cap", CAPS["max_postings_per_source"])), CAPS["max_postings_per_source"])
        kept = valid[:cap]
        postings.extend(kept)
        if src["adapter"] == "corpus":
            h.update(fetched=len(rows), kept=len(kept), rejected=len(rows) - len(valid), capped=max(0, len(valid) - cap))
        if h.get("status") == "ok" and not kept:
            h["status"] = "empty"
        health.append(h)
    step(trace, "fetch", sources=health)
    return postings, health


def normalize_and_dedupe(postings, trace):
    seen, out, dupes = {}, [], 0
    for p in postings:
        p = {k: (v.strip() if isinstance(v, str) else v) for k, v in p.items()}
        key = "|".join(re.sub(r"\s+", " ", str(p[f]).lower()) for f in ("company", "title", "location"))
        pid = p.get("id") or hashlib.sha1(key.encode()).hexdigest()[:10]
        p["id"] = pid
        if key in seen:
            seen[key]["sources"].append(p["source"])
            dupes += 1
            continue
        p["sources"] = [p.pop("source")]
        seen[key] = p
        out.append(p)
    total_cap = CAPS["max_postings_per_run"]
    capped = max(0, len(out) - total_cap)
    out = out[:total_cap]
    step(trace, "normalize", postings=len(out), duplicates_merged=dupes, capped=capped)
    return out


def deal_breaker(p, db):
    text = f"{p['title']} {p['text']}".lower()
    if db.get("remote_only") and not p.get("remote"):
        return "not remote"
    if db.get("min_pay") and p.get("pay_max") is not None and p["pay_max"] < db["min_pay"]:
        return f"pay below {db['min_pay']}"
    if db.get("min_pay") and p.get("pay_max") is None and db.get("require_pay_listed"):
        return "no pay listed"
    locs = [l.lower() for l in db.get("locations_any", [])]
    if locs and not p.get("remote") and not any(l in p["location"].lower() for l in locs):
        return "location not in list"
    for ind in db.get("exclude_industries", []):
        if ind.lower() == str(p.get("industry", "")).lower():
            return f"excluded industry: {ind}"
    for kw in db.get("exclude_keywords", []):
        if kw.lower() in text:
            return f"excluded keyword: {kw}"
    return None


def overlap(cv_text, p):
    """Cheap, visible prefilter: share of the posting's longer words that appear in the CV."""
    words = lambda s: {w for w in re.findall(r"[a-z]{5,}", s.lower())}
    pw, cw = words(p["title"] + " " + p["text"]), words(cv_text)
    return round(len(pw & cw) / max(1, len(pw)), 3)


def prepare(config):
    WORK.mkdir(exist_ok=True)
    trace = []
    run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if config.get("runs_today", 0) >= CAPS["max_runs_per_day"]:
        step(trace, "stop", cap="max_runs_per_day")
        (WORK / "results.json").write_text(json.dumps({"run": {"id": run_id, "status": "stopped", "cap_hit": "max_runs_per_day", "trace": trace}}, indent=2))
        print("Stopped: a run already happened today (course cap).")
        return

    searches = [s for s in config["searches"] if s.get("active")]
    if len(searches) > CAPS["max_searches"]:
        step(trace, "cap", cap="max_searches", dropped=[s["id"] for s in searches[CAPS["max_searches"]:]])
        searches = searches[: CAPS["max_searches"]]

    agent = config["agent"]
    postings, health = load_sources(agent, trace)
    postings = normalize_and_dedupe(postings, trace)

    per_search_cap = min(agent["settings"].get("max_judged_per_search", CAPS["max_judged_per_search"]), CAPS["max_judged_per_search"])
    items, filtered = [], []
    for s in searches:
        db = s["preferences"].get("deal_breakers", {})
        seen = set(config.get("seen", {}).get(s["id"], []))
        passed, already = [], 0
        for p in postings:
            if p["id"] in seen:
                already += 1
                continue
            reason = deal_breaker(p, db)
            if reason:
                filtered.append({"search": s["id"], "posting": p["id"], "title": p["title"], "company": p["company"], "reason": reason})
            else:
                passed.append((overlap(s["cv_text"], p), p))
        passed.sort(key=lambda t: -t[0])
        chosen = passed[:per_search_cap]
        step(trace, "filter", search=s["id"], already_matched=already, passed=len(passed), dropped=len(postings) - len(passed) - already,
             sent_to_judge=len(chosen), not_judged_over_cap=max(0, len(passed) - per_search_cap))
        for ov, p in chosen:
            items.append({"search_id": s["id"], "posting_id": p["id"], "overlap": ov,
                          "company": p["company"], "title": p["title"], "location": p["location"],
                          "remote": p.get("remote"), "pay_min": p.get("pay_min"), "pay_max": p.get("pay_max"),
                          "industry": p.get("industry"), "url": p.get("url") or None,
                          "sources": p.get("sources", []), "text": p["text"]})

    batch = {
        "run_id": run_id,
        "agent_version": agent["version"],
        "matcher_instructions": agent["matcher_instructions"],
        "searches": [{"id": s["id"], "name": s["name"], "cv_version": s["cv_version"],
                      "prefs_version": s["prefs_version"], "cv_text": s["cv_text"],
                      "dimensions": s["preferences"]["dimensions"]} for s in searches],
        "items": items,
        "answer_format": {
            "file": "work/judgments.json",
            "shape": [{"search_id": "...", "posting_id": "...",
                       "scores": {"<dimension key>": {"score": "1-5 or \"unknown\"", "reason": "one sentence",
                                                      "evidence": "exact words copied from the posting, empty if unknown"}}}],
        },
    }
    (WORK / "batch.json").write_text(json.dumps(batch, indent=2))
    (WORK / "state.json").write_text(json.dumps({"run_id": run_id, "started": trace[0]["at"] if trace else now(),
                                                 "trace": trace, "filtered": filtered, "sources": health}, indent=2))
    print(f"{run_id}: {len(postings)} postings, {len(items)} items to judge across {len(searches)} search(es). Wrote work/batch.json")


# ---------------------------------------------------------------- finish

def validate(j, item, dims):
    errors = []
    scores = j.get("scores", {})
    text = item["text"].lower()
    for d in dims:
        s = scores.get(d["key"])
        if s is None:
            errors.append(f"{d['key']}: missing")
            continue
        if s.get("score") == "unknown":
            continue
        if s.get("score") not in SCORES:
            errors.append(f"{d['key']}: score {s.get('score')!r} not 1-5 or unknown")
        ev = (s.get("evidence") or "").strip().lower()
        if not ev:
            errors.append(f"{d['key']}: no evidence")
        elif ev not in text and ev not in json.dumps(item).lower():
            errors.append(f"{d['key']}: evidence not found in posting")
    return errors


def weighted_total(scores, dims, unknown_policy):
    num = den = 0.0
    for d in dims:
        w = float(d["weight"])
        if w <= 0:
            continue
        s = scores[d["key"]]["score"]
        if s == "unknown":
            v = 0.5 if unknown_policy == "neutral" else 0.0
        else:
            v = (s - 1) / 4
        num += w * v
        den += w
    return round(100 * num / den) if den else 0


def finish(config):
    batch = json.loads((WORK / "batch.json").read_text())
    state = json.loads((WORK / "state.json").read_text())
    judgments = json.loads((WORK / "judgments.json").read_text())
    trace = state["trace"]
    prefs = {s["id"]: s["preferences"] for s in config["searches"]}
    dims = {s["id"]: s["dimensions"] for s in batch["searches"]}
    versions = {s["id"]: (s["cv_version"], s["prefs_version"]) for s in batch["searches"]}
    index = {(j["search_id"], j["posting_id"]): j for j in judgments}

    matches, rejected = [], []
    for item in batch["items"]:
        key = (item["search_id"], item["posting_id"])
        j = index.get(key)
        if j is None:
            rejected.append({"search": key[0], "posting": key[1], "errors": ["not judged"]})
            continue
        errs = validate(j, item, dims[key[0]])
        if errs:
            rejected.append({"search": key[0], "posting": key[1], "errors": errs})
            continue
        policy = prefs[key[0]].get("unknown_policy", "neutral")
        cv_v, pref_v = versions[key[0]]
        matches.append({
            "id": f"{key[0]}__{key[1]}", "run_id": batch["run_id"], "search_id": key[0], "posting_id": key[1],
            "company": item["company"], "title": item["title"], "location": item["location"],
            "pay_min": item["pay_min"], "pay_max": item["pay_max"], "industry": item["industry"],
            "text": item["text"], "url": item.get("url"), "sources": item.get("sources", []), "scores": j["scores"],
            "total": weighted_total(j["scores"], dims[key[0]], policy), "unknown_policy": policy,
            "agent_version": batch["agent_version"], "cv_version": cv_v, "prefs_version": pref_v,
            "first_seen": batch["run_id"], "first_seen_at": state["started"],
        })
    matches.sort(key=lambda m: -m["total"])
    step(trace, "judge", judged=len(judgments), accepted=len(matches), rejected=len(rejected), rejections=rejected)
    step(trace, "score", method="weighted average in code; unknown counts per search policy",
         top=[{"search": m["search_id"], "title": m["title"], "total": m["total"]} for m in matches[:5]])

    run = {"id": batch["run_id"], "status": "ok", "started": state["started"], "ended": now(),
           "agent_version": batch["agent_version"], "searches": [s["id"] for s in batch["searches"]],
           "sources": state["sources"], "filtered": state["filtered"], "matches": len(matches),
           "rejected": len(rejected), "trace": trace}
    (WORK / "results.json").write_text(json.dumps({"run": run, "matches": matches}, indent=2))
    print(f"{batch['run_id']}: {len(matches)} matches scored, {len(rejected)} judgments rejected. Wrote work/results.json")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("prepare", "finish"):
        sys.exit(__doc__)
    cfg = json.loads(Path(sys.argv[2]).read_text())
    {"prepare": prepare, "finish": finish}[sys.argv[1]](cfg)
