"""Suggested Profile changes, from the student's Good and Nope verdicts.

Code gathers the evidence and checks the answer; the model only proposes. Nothing here
changes a search: the page shows each suggestion, and the student applies it or not.

  uv run suggest.py prepare            work/db/ -> work/suggest.json (evidence, instructions, answer format)
  uv run suggest.py finish [--model <id>]
                                       work/suggestions.json -> checked -> work/out/suggestion.json,
                                       to write to the `suggestions` collection under the id it prints
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import engine

HERE = Path(__file__).parent
WORK = HERE / "work"
MAX_PER_SEARCH = 3
MAX_POSTS = 40
LIST_TARGETS = {"target_roles": "Target roles", "keywords": "Background keywords", "industries": "Target industries"}


def body(path):
    d = json.loads(path.read_text())
    return d.get("data", d)


def docs(name):
    d = WORK / "db" / name
    return {p.stem: body(p) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def now():
    return datetime.now(timezone.utc).isoformat()


def pairs_agree(good, nope):
    """Share of (Good, Nope) pairs where the Good one has the higher value; ties count half."""
    if not good or not nope:
        return None
    w = sum(1 if g > n else .5 if g == n else 0 for g in good for n in nope)
    return round(100 * w / (len(good) * len(nope)))


def total(scores, dims, policy):
    """The engine's own weighted total; a dimension added after a post was scored counts as unknown."""
    full = {d["key"]: scores.get(d["key"]) or {"score": "unknown"} for d in dims}
    return engine.weighted_total(full, dims, policy)


def judged(search_id, matches, judgments):
    out = []
    for mid, m in matches.items():
        j = judgments.get(mid) or {}
        if m.get("search_id") == search_id and j.get("verdict") in ("accept", "dismiss"):
            out.append((m, j))
    return out


def prepare():
    searches, matches, judgments = docs("searches"), docs("matches"), docs("judgments")
    agent = body(WORK / "db" / "agent" / "current.json")
    out = []
    for sid, s in searches.items():
        if not s.get("active", True):
            continue
        prefs = s.get("preferences", {})
        dims = prefs.get("dimensions", [])
        rows = judged(sid, matches, judgments)
        good = [m for m, j in rows if j["verdict"] == "accept"]
        nope = [m for m, j in rows if j["verdict"] == "dismiss"]
        if not good or not nope:
            continue
        per_dim = []
        for d in dims:
            val = lambda m: (m.get("scores", {}).get(d["key"]) or {}).get("score")
            g = [val(m) for m in good if isinstance(val(m), (int, float))]
            n = [val(m) for m in nope if isinstance(val(m), (int, float))]
            per_dim.append({"key": d["key"], "name": d["name"], "weight": d["weight"], "agreement": pairs_agree(g, n),
                            "good_avg": round(sum(g) / len(g), 1) if g else None, "nope_avg": round(sum(n) / len(n), 1) if n else None})
        dim_names = {d["key"]: d["name"] for d in dims}
        good_avg = sum(m["total"] for m in good) / len(good)
        nope_avg = sum(m["total"] for m in nope) / len(nope)
        # Disagreements first, so a long history still fits.
        def miss(mj):
            m, j = mj
            return -(m["total"] - nope_avg) if j["verdict"] == "accept" else (m["total"] - good_avg)
        posts = []
        for m, j in sorted(rows, key=miss, reverse=True)[:MAX_POSTS]:
            posts.append({"match_id": m["id"], "title": m["title"], "company": m["company"], "location": m.get("location"),
                          "industry": m.get("industry"), "total": m["total"], "verdict": "Good" if j["verdict"] == "accept" else "Nope",
                          "student_reason": dim_names.get(j.get("main_dimension"), j.get("main_dimension")), "student_note": j.get("reason") or "",
                          "scores": {k: {"score": v.get("score"), "reason": v.get("reason")} for k, v in (m.get("scores") or {}).items()}})
        out.append({"search_id": sid, "prefs_version": s.get("prefs_version"),
                    "agreement": pairs_agree([m["total"] for m in good], [m["total"] for m in nope]),
                    "good": len(good), "nope": len(nope), "by_dimension": per_dim,
                    "profile": {"dimensions": dims, "target_roles": s.get("target_roles", []), "keywords": s.get("keywords", []),
                                "industries": s.get("industries", []), "unknown_policy": prefs.get("unknown_policy", "neutral")},
                    "posts": posts})
    task = {
        "agent_version": agent.get("version"),
        "matcher_instructions": agent.get("matcher_instructions", ""),
        "instructions": (
            f"For each search, propose at most {MAX_PER_SEARCH} changes to its Profile that would make the agent's scores agree better "
            "with the student's verdicts. Agreement is how often a Good post scores above a Nope post. Use `by_dimension` to see which "
            "dimensions mislead (agreement under 50% means that dimension rates Nope posts higher than Good ones) and `posts` for the cases. "
            "Allowed targets: `weights` (a full map of every dimension key to a whole number, adding up to 100), `rubric:<dimension key>` "
            "(the new rubric text), `target_roles`, `keywords` or `industries` (the full new list). Never propose changes to filters such as "
            "locations or pay; those are the student's rules. Prefer the smallest change that fixes a pattern seen in two or more posts. "
            "Write `why` as one plain sentence to the student, naming the posts' pattern, not the statistic. Cite the posts in `posts` by match_id. "
            "Weight changes are checked in code on the same judged posts and dropped unless they raise agreement. "
            "If nothing would clearly help, return no suggestions for that search."),
        "searches": out,
        "answer_format": {"file": "work/suggestions.json",
                          "shape": {"suggestions": [{"search_id": "...", "target": "weights | rubric:<key> | target_roles | keywords | industries",
                                                     "proposed": "map, text or list, per target", "why": "one sentence", "posts": ["match_id"]}]}},
    }
    (WORK / "suggest.json").write_text(json.dumps(task, indent=1))
    n = sum(len(s["posts"]) for s in out)
    print(f"suggest: {len(out)} search(es) with Good and Nope verdicts, {n} judged posts. Wrote work/suggest.json"
          if out else "suggest: no search has both Good and Nope verdicts yet; nothing to suggest.")


def check(sug, s):
    """Errors in one suggestion, against its search's evidence. Returns (errors, current value)."""
    prof, target, p = s["profile"], sug.get("target", ""), sug.get("proposed")
    keys = [d["key"] for d in prof["dimensions"]]
    if target == "weights":
        if not isinstance(p, dict) or set(p) != set(keys):
            return ["weights must name every dimension"], None
        if not all(isinstance(v, int) and 0 <= v <= 100 for v in p.values()) or sum(p.values()) != 100:
            return ["weights must be whole numbers adding up to 100"], None
        return [], {d["key"]: d["weight"] for d in prof["dimensions"]}
    if target.startswith("rubric:"):
        k = target.split(":", 1)[1]
        if k not in keys:
            return [f"no dimension {k!r}"], None
        if not isinstance(p, str) or not p.strip() or len(p) > 800:
            return ["rubric must be text, at most 800 characters"], None
        return [], next(d["rubric"] for d in prof["dimensions"] if d["key"] == k)
    if target in LIST_TARGETS:
        if not isinstance(p, list) or not all(isinstance(x, str) and x.strip() for x in p) or len(p) > 60:
            return ["list must be up to 60 words or phrases"], None
        return [], prof[target]
    return [f"unknown target {target!r}"], None


def label(target, s):
    if target == "weights":
        return "Weights"
    if target.startswith("rubric:"):
        k = target.split(":", 1)[1]
        name = next((d["name"] for d in s["profile"]["dimensions"] if d["key"] == k), k)
        return f"{name} rubric"
    return LIST_TARGETS[target]


def predicted(weights, s, matches, judgments):
    """Agreement on the same judged posts if the scores stayed and only the weights changed. Exact, because totals are code."""
    dims = [{**d, "weight": weights[d["key"]]} for d in s["profile"]["dimensions"]]
    policy = s["profile"]["unknown_policy"]
    rows = judged(s["search_id"], matches, judgments)
    g = [total(m.get("scores", {}), dims, policy) for m, j in rows if j["verdict"] == "accept"]
    n = [total(m.get("scores", {}), dims, policy) for m, j in rows if j["verdict"] == "dismiss"]
    return pairs_agree(g, n)


def finish(model=None):
    task = json.loads((WORK / "suggest.json").read_text())
    answer = json.loads((WORK / "suggestions.json").read_text()) if (WORK / "suggestions.json").exists() else {}
    matches, judgments = docs("matches"), docs("judgments")
    by_id = {s["search_id"]: s for s in task["searches"]}
    items, rejected, count = [], [], {}
    for sug in answer.get("suggestions", []):
        s = by_id.get(sug.get("search_id"))
        if not s:
            rejected.append({"suggestion": sug, "errors": ["unknown search"]})
            continue
        errs, current = check(sug, s)
        known = {p["match_id"] for p in s["posts"]}
        cited = [x for x in sug.get("posts", []) if x in known]
        if not cited:
            errs.append("cites no judged post")
        if not errs and count.get(s["search_id"], 0) >= MAX_PER_SEARCH:
            errs.append(f"more than {MAX_PER_SEARCH} for this search")
        if errs:
            rejected.append({"suggestion": sug, "errors": errs})
            continue
        if sug["target"] == "weights":
            after = predicted(sug["proposed"], s, matches, judgments)
            before = predicted(current, s, matches, judgments)
            if after is None or before is None or after <= before:
                rejected.append({"suggestion": sug, "errors": [f"would not raise agreement on the judged posts ({before}% to {after}%)"]})
                continue
        count[s["search_id"]] = count.get(s["search_id"], 0) + 1
        item = {"search_id": s["search_id"], "target": sug["target"], "label": label(sug["target"], s), "current": current,
                "proposed": sug["proposed"], "why": str(sug.get("why", ""))[:400], "posts": cited, "status": "open"}
        if sug["target"] == "weights":
            item["predicted"] = {"before": before, "after": after}
        items.append(item)
    at = now()
    doc_id = "s-" + at[:19].replace(":", "").replace("-", "")
    doc = {"id": doc_id, "at": at, "model": model, "agent_version": task["agent_version"],
           "searches": [{k: s[k] for k in ("search_id", "prefs_version", "agreement", "good", "nope", "by_dimension")} for s in task["searches"]],
           "items": items, "rejected": rejected}
    out = WORK / "out"
    out.mkdir(exist_ok=True)
    (out / "suggestion.json").write_text(json.dumps(doc, indent=1))
    print(f"suggest: {len(items)} suggestion(s), {len(rejected)} rejected. Write work/out/suggestion.json to suggestions/{doc_id}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare()
    elif cmd == "finish":
        a = sys.argv[2:]
        finish(a[a.index("--model") + 1] if "--model" in a and len(a) > a.index("--model") + 1 else None)
    else:
        sys.exit(__doc__)
