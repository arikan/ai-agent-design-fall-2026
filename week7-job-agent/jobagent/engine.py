"""Job agent engine, minimal version. Python standard library only.

The engine is the deterministic shell around the agent. It never calls a model.
Claude (the scheduled session) does the judging between the two commands:

  uv run jobagent engine prepare  config.json   -> work/batch.json   (what Claude must judge)
  uv run jobagent engine finish   config.json   -> work/results.json (matches, run record, trace)

Everything the engine decides is written to the trace, so a run can be read step by step.
"""

import hashlib
import json
from collections import Counter
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapters.text import pay_match

HERE = Path(__file__).resolve().parents[1]     # the project folder: work/, defaults/, caps.json
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


RANK_TEXT_CHARS = 1500    # what filters and the ranking read of each posting, here and in the page's preview
JUDGE_TEXT_CHARS = 3000   # what the judge reads of each posting: role, requirements and pay are near the top
FILTERED_KEPT = 100   # deal-breaker drops listed one by one in a run record; the rest are counted


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
    capped, capped_by_source = max(0, len(out) - total_cap), {}
    if capped:
        # Over the run's limit: take postings from every source in turn, so the cut falls evenly
        # instead of dropping whole sources at the end of the list.
        by_src = {}
        for p in out:
            by_src.setdefault(p["sources"][0], []).append(p)
        queues, kept = [list(v) for v in by_src.values()], []
        while len(kept) < total_cap and any(queues):
            for q in queues:
                if q and len(kept) < total_cap:
                    kept.append(q.pop(0))
        kept_ids = {p["id"] for p in kept}
        for src, ps in by_src.items():
            n = sum(1 for p in ps if p["id"] not in kept_ids)
            if n:
                capped_by_source[src] = n
        out = [p for p in out if p["id"] in kept_ids]
    step(trace, "normalize", postings=len(out), duplicates_merged=dupes, capped=capped, capped_by_source=capped_by_source)
    return out


SNAPSHOT_FIELDS = ("id", "title", "company", "location", "remote", "pay_min", "pay_max", "industry", "category", "url", "sources")


def judge_text(p):
    """What Claude reads of a posting: its start, plus the pay passage when that sits further down.
    Many boards put pay at the very end, past the cut, which left Compensation fit unknown
    even when the posting lists pay."""
    text = p["text"]
    head = text[:JUDGE_TEXT_CHARS]
    if p.get("pay_min") is None and p.get("pay_max") is None or len(text) <= JUDGE_TEXT_CHARS:
        return head
    tail = text[JUDGE_TEXT_CHARS:]
    m = pay_match(tail) or re.search(r"\$\s?\d", tail)
    if not m:
        return head
    start = max(tail.rfind(". ", 0, m.start()) + 2, m.start() - 250, 0)
    end = tail.find(". ", m.end())
    end = min(end + 1 if end >= 0 else len(tail), m.end() + 250)
    return f"{head} … {tail[start:end].strip()}"


def prompt_sample(batch, judgments, matches):
    """One real example of what Claude read and answered this run, in labeled parts, for the
    Agent tab: the run's own instruction, the agent's, the user's, the post, and the answer."""
    if not matches:
        return None
    m = matches[0]
    item = next(i for i in batch["items"] if i["search_id"] == m["search_id"] and i["posting_id"] == m["posting_id"])
    search = next(s for s in batch["searches"] if s["id"] == m["search_id"])
    run_md = (HERE / "RUN.md").read_text()
    step = next((l.strip() for l in run_md.splitlines() if l.strip().startswith("5. **Judge**")), "")
    dims = "\n".join(f"{d['name']} ({d.get('weight')}% weight): {d.get('rubric', '')}" + (f" {d['inputs']}" if d.get("inputs") else "")
                     for d in search["dimensions"])
    pay = "" if item.get("pay_min") is None and item.get("pay_max") is None else f"Pay: {item.get('pay_min')} to {item.get('pay_max')}\n"
    answer = next((j for j in judgments if j["search_id"] == m["search_id"] and j["posting_id"] == m["posting_id"]), {})
    parts = [
        {"label": "How to judge", "from": "RUN.md, the run's own instructions", "text": step},
        {"label": "Scoring instructions", "from": "Agent tab, Settings", "text": batch["matcher_instructions"]},
        {"label": "Your dimensions", "from": "Profile tab", "text": dims},
        {"label": "Your CV", "from": "Profile tab", "text": search.get("cv_text") or "(none)"},
        {"label": "The post", "from": ", ".join(item.get("sources") or []) or "job board",
         "text": f"{item['title']} · {item['company']} · {item['location']}\n{pay}\n{item['text']}"},
        {"label": "Answer format", "from": "engine.py", "text": json.dumps(batch["answer_format"]["shape"], indent=1)},
        {"label": "What the model answered", "from": "the model", "text": json.dumps(answer.get("scores", {}), indent=1)},
    ]
    return {"posting_id": m["posting_id"], "title": item["title"], "company": item["company"], "total": m["total"], "parts": parts}


def snapshot_item(p):
    """What the page keeps of a collected posting: the fields the ranking and the judge use."""
    return {**{k: p.get(k) for k in SNAPSHOT_FIELDS}, "text": p["text"][:RANK_TEXT_CHARS]}


def for_ranking(p):
    """The posting as filters and the ranking see it: the start of its text, the same in the page's preview."""
    return {**p, "text": p["text"][:RANK_TEXT_CHARS]}


ROLE_CASE_ROLES = ["CPO", "VP of Product", "Head of Product", "Director of Product", "Entrepreneur in Residence", "Senior Product Designer"]
ROLE_CASE_TITLES = ["Director, Product Management", "Product Director", "SVP, Product", "Vice President of Product",
                    "Chief Product Officer (CPO)", "Entrepreneur-in-Residence", "EIR, Fintech", "Sr. Product Designer",
                    "Senior Product Manager", "Director of Engineering", "Head of Product & Design", "Staff+ Software Engineer"]


def rank_fixture():
    """The ranking of the corpus postings for the example search, as the page's JavaScript must reproduce it.
    `node tests/rank_test.js` compares the two."""
    cfg = json.loads((HERE / "examples" / "config.example.json").read_text())
    search = cfg["searches"][0]
    rows = load_jsonl(HERE / "corpus" / "postings.jsonl")
    for r in rows:
        r["source"] = "corpus"
    postings = [snapshot_item(p) for p in normalize_and_dedupe(rows, [])]
    db = search["preferences"].get("deal_breakers", {})
    out = {"search": {k: search.get(k) for k in ("target_roles", "keywords", "industries", "cv_text")}, "deal_breakers": db,
           "postings": postings,
           "role_cases": {"roles": ROLE_CASE_ROLES, "titles": ROLE_CASE_TITLES,
                          "expected": [role_hit(ROLE_CASE_ROLES, {"title": t}) for t in ROLE_CASE_TITLES]},
           "pay_cases": [{"target": 250000, "pay_max": m, "expected": deal_breaker(
                {"title": "x", "text": "", "location": "", "remote": True, "pay_max": m}, {"min_pay": 250000})}
                         for m in (None, 300000, 190000, 187500, 187499, 120000)],
           "title_cases": [{"title": t, "words": ["marketing", "chief of staff"], "expected": deal_breaker(
                {"title": t, "text": "", "location": "", "remote": True, "pay_max": None}, {"exclude_title_words": ["marketing", "chief of staff"]})}
                           for t in ("Product Marketing Lead", "Head of Product, Go-to-Market", "Marketplace Product Lead", "Chief of Staff Director, Product",
                                     "MARKETING Director", "Head of Product")],
           "expected": [{"id": p["id"], "dropped": deal_breaker(p, db), "score": prefilter_score(search, p)} for p in postings]}
    (HERE / "tests").mkdir(exist_ok=True)
    (HERE / "tests" / "rank_fixture.json").write_text(json.dumps(out, indent=1))
    print(f"wrote tests/rank_fixture.json: {len(postings)} postings")


def drop_detail(p, reason, db):
    """The reason in words a user can check against the posting and their settings."""
    money = lambda n: f"${n:,.0f}"
    if reason == "location not in list":
        return f"Location {p.get('location') or 'not given'} matches none of {', '.join(db.get('locations_any', []))}, in the location or the title, and it isn't marked remote"
    if reason == "not remote":
        return f"Not marked remote ({p.get('location') or 'no location given'})"
    if reason.startswith("pay far below"):
        return f"Pay tops out at {money(p['pay_max'])}, more than {round(PAY_SLACK * 100)}% below your {money(db['min_pay'])} target"
    if reason == "no pay listed":
        return "No pay listed, and you require it"
    if reason.startswith("excluded title word"):
        return f"Title has \"{reason.split(': ', 1)[1]}\", which you excluded"
    return reason[0].upper() + reason[1:]


# Target pay is a preference, not a floor: a post paying a bit less can still be a good one, and
# Compensation fit scores how well pay fits. Only posts far below the target are dropped, so they
# don't take the model's few slots.
PAY_SLACK = 0.25


def pay_cutoff(target):
    return target * (1 - PAY_SLACK)


def deal_breaker(p, db):
    text = f"{p['title']} {p['text']}".lower()
    if db.get("remote_only") and not p.get("remote"):
        return "not remote"
    if db.get("min_pay") and p.get("pay_max") is not None and p["pay_max"] < pay_cutoff(db["min_pay"]):
        return f"pay far below {db['min_pay']}"
    if db.get("min_pay") and p.get("pay_max") is None and db.get("require_pay_listed"):
        return "no pay listed"
    locs = [l.lower() for l in db.get("locations_any", [])]
    where = f"{p['location']} | {p['title']}".lower()     # some boards put the location only in the title
    if locs and not p.get("remote") and not any(l in where for l in locs):
        return "location not in list"
    for ind in db.get("exclude_industries", []):
        if ind.lower() == str(p.get("industry", "")).lower():
            return f"excluded industry: {ind}"
    for kw in db.get("exclude_keywords", []):
        if kw.lower() in text:
            return f"excluded keyword: {kw}"
    for w in db.get("exclude_title_words", []):
        if title_has(p["title"], w):
            return f"excluded title word: {w}"
    return None


def title_has(title, word):
    """A word or phrase in the title, as a whole word, ignoring case: "marketing" matches "Product Marketing Lead",
    not "Go-to-market". Only the title, since descriptions of good jobs mention marketing too."""
    w = word.strip().lower()
    return bool(w) and re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", title.lower()) is not None


def overlap(cv_text, p):
    """Share of the posting's longer words that also appear in the CV."""
    words = lambda s: {w for w in re.findall(r"[a-z]{5,}", s.lower())}
    pw, cw = words(p["title"] + " " + p["text"]), words(cv_text or "")
    return len(pw & cw) / max(1, len(pw))


def keyword_hits(keywords, p):
    """Share of the search's keywords found in the posting; a keyword in the title counts double."""
    if not keywords:
        return 0.0
    title, text = p["title"].lower(), p["text"].lower()
    pat = lambda k: re.compile(r"(?<![a-z])" + re.escape(k.lower()) + r"(?![a-z])")
    score = sum(2 if pat(k).search(title) else 1 if pat(k).search(text) else 0 for k in keywords)
    return score / (2 * len(keywords))


# Which of the user's lists informs which dimension. The matcher sees each list
# next to the dimension it belongs to, so a score can be traced to what it used.
DIMENSION_INPUTS = {
    "role": ("target_roles", "The user's target roles"),
    "industry": ("industries", "The user's target industries"),
    "background": ("keywords", "The user's background keywords"),
}


def with_inputs(search):
    """The search's dimensions, each with the user's own input that applies to it."""
    out = []
    for d in search["preferences"]["dimensions"]:
        d = dict(d)
        field, label = DIMENSION_INPUTS.get(d["key"], (None, None))
        parts = []
        if field and search.get(field):
            parts.append(f"{label}: {', '.join(search[field])}.")
        if d["key"] == "compensation":
            db = search["preferences"].get("deal_breakers", {})
            cur = db.get("currency") or "USD"
            pay = [f"target {db['min_pay']:,.0f} {cur} (a bit below can still fit)" if db.get("min_pay") else "",
                   f"preferred {db['preferred_pay']:,.0f} {cur}" if db.get("preferred_pay") else ""]
            if any(pay):
                parts.append(f"The user's total compensation targets: {', '.join(x for x in pay if x)} a year.")
        if d["key"] == "background":
            parts.append("Compare them, and the CV text if there is one, with the posting's requirements."
                         if (search.get("cv_text") or "").strip() or search.get("keywords")
                         else "No CV or background keywords given: score unknown.")
        if parts:
            d["inputs"] = " ".join(parts)
        out.append(d)
    return out


TITLE_PHRASES = (("vice president", "vp"), ("chief product officer", "cpo"), ("entrepreneur in residence", "eir"),
                 ("senior", "sr"))
TITLE_WORDS = {"svp": "vp", "evp": "vp", "avp": "vp"}           # every VP grade counts as VP
TITLE_NOISE = {"of", "the", "and", "for", "a", "an", "in", "at", "to", "management"}   # "Product Management" is "Product"


def title_words(t):
    """The words that identify a job title, so 'VP, Product', 'Vice President of Product' and
    'SVP Product' all become {'vp', 'product'}, and 'Director, Product Management' becomes {'director', 'product'}."""
    t = " " + re.sub(r"[^a-z0-9]+", " ", t.lower().replace("&", " and ")) + " "
    for long, short in TITLE_PHRASES:
        t = t.replace(f" {long} ", f" {short} ")
    return {TITLE_WORDS.get(w, w) for w in re.findall(r"[a-z0-9]+", t)} - TITLE_NOISE


def role_hit(roles, p):
    """The first target role whose words all appear in the posting's title, in any order, or None."""
    title = title_words(p["title"])
    return next((r for r in roles if title_words(r) and title_words(r) <= title), None)


def role_match(roles, p):
    """1 when a target role matches the posting's title, else 0."""
    return 1.0 if role_hit(roles, p) else 0.0


def prefilter_score(search, p):
    """Cheap, visible ranking that decides which postings get scored by Claude.
    A target role in the title counts most, then keywords, then industries, then word
    overlap with the CV. Each part only counts when the search has it."""
    parts = []
    if search.get("target_roles"):
        parts.append((0.45, role_match(search["target_roles"], p)))
    if search.get("keywords"):
        parts.append((0.3, keyword_hits(search["keywords"], p)))
    if search.get("industries"):
        q = {**p, "text": f"{p['text']} {p.get('industry') or ''} {p.get('category') or ''}"}
        parts.append((0.1, 1.0 if keyword_hits(search["industries"], q) > 0 else 0.0))
    if (search.get("cv_text") or "").strip():
        parts.append((0.15, overlap(search["cv_text"], p)))
    total = sum(w for w, _ in parts)
    return round(sum(w * v for w, v in parts) / total, 3) if total else 0.0


def prepare(config):
    WORK.mkdir(exist_ok=True)
    trace = []
    run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    trigger = config.get("trigger", "scheduled")
    if trigger == "manual" and config.get("manual_runs_24h", 0) >= CAPS["max_manual_runs_per_day"]:
        allowed_at = (datetime.fromisoformat(config["manual_runs_since"][0]) + timedelta(hours=24)).isoformat()
        reason = (f"{config['manual_runs_24h']} runs were started by hand in the last 24 hours, the course limit. "
                  f"The next run by hand is allowed after {allowed_at[:16].replace('T', ' ')} UTC; the morning run is not affected.")
        step(trace, "stop", cap="max_manual_runs_per_day", reason=reason)
        (WORK / "results.json").write_text(json.dumps({"run": {"id": run_id, "status": "stopped", "cap_hit": "max_manual_runs_per_day",
                                                                "reason": reason, "allowed_at": allowed_at, "trigger": trigger,
                                                                "agent_version": config["agent"]["version"], "started": trace[0]["at"],
                                                                "ended": now(), "matches": 0, "trace": trace}}, indent=2))
        print("Stopped: " + reason)
        return

    searches = [s for s in config["searches"] if s.get("active")]
    if len(searches) > CAPS["max_searches"]:
        step(trace, "cap", cap="max_searches", dropped=[s["id"] for s in searches[CAPS["max_searches"]:]])
        searches = searches[: CAPS["max_searches"]]

    agent = config["agent"]
    postings, health = load_sources(agent, trace)
    postings = normalize_and_dedupe(postings, trace)
    (WORK / "postings.json").write_text(json.dumps([snapshot_item(p) for p in postings]))

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
            rp = for_ranking(p)
            reason = deal_breaker(rp, db)
            if reason:
                filtered.append({"search": s["id"], "posting": p["id"], "title": p["title"], "company": p["company"], "reason": reason,
                                 "detail": drop_detail(rp, reason, db)})
            else:
                passed.append((prefilter_score(s, rp), p))
        passed.sort(key=lambda t: -t[0])
        floor = min(max(int(agent["settings"].get("min_rank_score", 0)), 0), 100) / 100
        eligible = [t for t in passed if t[0] >= floor]       # below the floor is not worth a score
        again = set(config.get("rescore", {}).get(s["id"], []))
        forced = [t for t in passed if t[1]["id"] in again]          # asked to be scored again, whatever their rank
        chosen = forced + [t for t in eligible if t[1]["id"] not in again][:per_search_cap]
        # Per source: how many of its posts passed the filters, ranked high enough, and were scored.
        # The Sources tab shows it, and suggestions use it to find boards that never yield anything for you.
        by_source = {}
        for group, key in ((passed, "passed"), (eligible, "ranked"), (chosen, "scored")):
            for _, p in group:
                src = (p.get("sources") or ["?"])[0]
                by_source.setdefault(src, {"passed": 0, "ranked": 0, "scored": 0})[key] += 1
        step(trace, "filter", search=s["id"], already_matched=already, passed=len(passed), dropped=len(postings) - len(passed) - already,
             sent_to_judge=len(chosen), rescored=len(forced), rescore_not_found=sorted(again - {t[1]["id"] for t in forced}), below_min_rank=len(passed) - len(eligible), min_rank_score=round(floor * 100),
             not_judged_over_cap=max(0, len(eligible) - per_search_cap), by_source=by_source,
             # The best posts the minimum rank kept from the model, so an empty run can say what it missed.
             best_below_min=[{"title": p["title"], "company": p["company"], "rank": round(sc * 100)}
                             for sc, p in passed if sc < floor][:3])
        for ov, p in chosen:
            items.append({"search_id": s["id"], "posting_id": p["id"], "prefilter": ov,
                          "company": p["company"], "title": p["title"], "location": p["location"],
                          "remote": p.get("remote"), "pay_min": p.get("pay_min"), "pay_max": p.get("pay_max"),
                          "industry": p.get("industry"), "url": p.get("url") or None,
                          "sources": p.get("sources", []), "text": judge_text(p)})

    batch = {
        "run_id": run_id,
        "agent_version": agent["version"],
        "matcher_instructions": agent["matcher_instructions"],
        "searches": [{"id": s["id"], "name": s["name"], "cv_version": s["cv_version"],
                      "prefs_version": s["prefs_version"], "cv_text": s.get("cv_text", ""), "keywords": s.get("keywords", []),
                      "target_roles": s.get("target_roles", []), "industries": s.get("industries", []),
                      "dimensions": with_inputs(s)} for s in searches],
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
            "rescored": item["posting_id"] in set(config.get("rescore", {}).get(item["search_id"], [])),
        })
    matches.sort(key=lambda m: -m["total"])
    step(trace, "judge", judged=len(judgments), accepted=len(matches), rejected=len(rejected), rejections=rejected)
    step(trace, "score", method="weighted average in code; unknown counts per search policy",
         top=[{"search": m["search_id"], "title": m["title"], "total": m["total"]} for m in matches[:5]])

    run = {"id": batch["run_id"], "status": "ok", "trigger": config.get("trigger", "scheduled"),
           "prompt_sample": prompt_sample(batch, judgments, matches),
           "started": state["started"], "ended": now(), "agent_version": batch["agent_version"], "searches": [s["id"] for s in batch["searches"]],
           "sources": state["sources"], "filtered": state["filtered"][:FILTERED_KEPT],
           "filtered_total": len(state["filtered"]), "filtered_by_reason": dict(Counter(f["reason"] for f in state["filtered"]).most_common()),
           "matches": len(matches),
           "rejected": len(rejected), "trace": trace}
    (WORK / "results.json").write_text(json.dumps({"run": run, "matches": matches}, indent=2))
    print(f"{batch['run_id']}: {len(matches)} matches scored, {len(rejected)} judgments rejected. Wrote work/results.json")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "rank-fixture":
        rank_fixture()
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] not in ("prepare", "finish"):
        sys.exit(__doc__)
    cfg = json.loads(Path(sys.argv[2]).read_text())
    {"prepare": prepare, "finish": finish}[sys.argv[1]](cfg)


if __name__ == "__main__":
    main()
