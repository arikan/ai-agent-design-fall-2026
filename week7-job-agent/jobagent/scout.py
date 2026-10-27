"""Does a team of scouts find better job boards than one? An experiment, on your own profile and verdicts.

  uv run jobagent scout [--n 12] [--model <id>]     -> a comparison table, and work/scout-compare.json

Both arms get the same context: your profile, the companies behind your Good and Nope posts, and the boards you
already read. Each arm proposes companies; code then finds each company's board and measures it the way a run
would: jobs listed, how many pass your filters, how many rank high enough for the model to read.

- Solo: one model call names n companies.
- Team: three scouts, each with its own brief, name n/3 companies each, in parallel; a lead (code) merges them
  and drops duplicates. Same model and the same total number of names, so a difference comes from splitting the
  work, not from a better model or a bigger ask.

Read the result as: which arm found more boards that would reach the model, at what cost in tokens and time.
One run is one sample; run it a few times before believing a difference.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import boards
from . import model as llm
from .suggest import docs, body, WORK, active_search, min_rank

BRIEFS = {
    "peers": "Name companies that are close peers of the companies behind the Good posts: same field, same stage, similar product.",
    "industry": "Name companies in the person's target industries that are likely hiring senior product leaders now. Avoid close copies of the Good companies; widen the field.",
    "investors": "Think of the investors that back companies like the Good ones, and name companies from those portfolios that fit the person.",
}


def squash(t):
    return re.sub(r"[^a-z0-9]+", "", str(t).lower())


def context():
    search = active_search() or {}
    matches, judgments = docs("matches"), docs("judgments")
    agent = body(WORK / "db" / "agent" / "current.json")
    good = sorted({f"{m['title']} at {m['company']}" for k, m in matches.items() if (judgments.get(k) or {}).get("verdict") == "accept"})
    nope = sorted({m["company"] for k, m in matches.items() if (judgments.get(k) or {}).get("verdict") == "dismiss"})
    have = [s["id"] for s in agent.get("sources", [])]
    have_names = sorted({(s.get("config") or {}).get("company_name") or s["id"] for s in agent.get("sources", [])})
    profile = {k: search.get(k) for k in ("target_roles", "industries", "keywords")}
    profile["locations"] = (search.get("preferences", {}).get("deal_breakers") or {}).get("locations_any")
    return search, have, {"profile": profile, "good_posts": good, "nope_companies": nope, "already_read": have_names}


def ask(brief, n, ctx, model):
    system = ("You find companies whose own job boards would carry jobs this person wants. Answer with JSON only: "
              '{"companies": [{"company": "name", "why": "a few words"}]}. Name real companies with their usual names; '
              "skip any company in already_read.")
    user = json.dumps({**ctx, "task": f"{brief} Name {n}."}, indent=1)
    t = time.time()
    text, u = llm.complete(system, user, model)
    try:
        names = [c["company"] for c in llm.json_block(text).get("companies", []) if c.get("company")]
    except Exception:
        names = []
    return names, {**u, "seconds": round(time.time() - t, 1)}


def measure(names, search, have, floor):
    with ThreadPoolExecutor(max_workers=6) as pool:
        ys = list(pool.map(lambda n: boards.board_yield(n, search, have, floor), names))
    return [{"company": n, **(y or {"id": None})} for n, y in zip(names, ys)]


def summary(rows, usage):
    found = [r for r in rows if r.get("id")]
    return {"named": len(rows), "boards_found": len(found), "boards_with_matches": sum(1 for r in found if r.get("ranked")),
            "pass_filters": sum(r.get("passed", 0) for r in found), "would_reach_model": sum(r.get("ranked", 0) for r in found),
            "reach_per_board": round(sum(r.get("ranked", 0) for r in found) / len(found), 2) if found else 0,
            "model_calls": len(usage), "tokens": sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in usage),
            "seconds": max((u["seconds"] for u in usage), default=0)}


def main(argv):
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 12
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    search, have, ctx = context()
    if not search:
        sys.exit("No active search in work/db. Start the agent once (uv run jobagent serve) first.")
    floor = min_rank()
    print(f"scout: {len(ctx['good_posts'])} Good posts, {len(have)} boards already read, minimum rank {round(floor * 100)}")

    print("scout: solo, one call")
    solo_names, su = ask("Cast a wide net across everything in the profile and the Good posts.", n, ctx, model)
    print(f"scout: team, {len(BRIEFS)} scouts in parallel")
    with ThreadPoolExecutor(max_workers=len(BRIEFS)) as pool:
        team = list(pool.map(lambda b: ask(b, max(2, -(-n // len(BRIEFS))), ctx, model), BRIEFS.values()))
    seen, team_names, by_scout = set(), [], {}
    for key, (names, _) in zip(BRIEFS, team):
        by_scout[key] = names
        for x in names:                     # the lead: merge, drop duplicates
            if squash(x) not in seen:
                seen.add(squash(x))
                team_names.append(x)

    print(f"scout: measuring {len(set(map(squash, solo_names)) | seen)} companies' boards")
    solo_rows = measure(solo_names, search, have, floor)
    team_rows = measure(team_names, search, have, floor)
    out = {"n": n, "floor": floor, "solo": {"summary": summary(solo_rows, [su]), "companies": solo_rows},
           "team": {"summary": summary(team_rows, [u for _, u in team]), "companies": team_rows, "by_scout": by_scout},
           "overlap": sorted({squash(x) for x in solo_names} & seen)}
    WORK.mkdir(exist_ok=True)
    (WORK / "scout-compare.json").write_text(json.dumps(out, indent=1))

    rows = [("companies named", "named"), ("boards found", "boards_found"), ("boards with posts for the model", "boards_with_matches"),
            ("posts that pass your filters", "pass_filters"), ("posts that would reach the model", "would_reach_model"), ("  per board found", "reach_per_board"),
            ("model calls", "model_calls"), ("tokens", "tokens"), ("seconds (longest call)", "seconds")]
    print(f"\n{'':34}{'solo':>8}{'team':>8}")
    for label, k in rows:
        print(f"{label:34}{out['solo']['summary'][k]:>8}{out['team']['summary'][k]:>8}")
    print(f"\nnamed by both: {len(out['overlap'])}")
    best = sorted([r for r in solo_rows + team_rows if r.get("ranked")], key=lambda r: -r["ranked"])
    for r in {r["id"]: r for r in best}.values():
        print(f"  {r['id']:<32} {r['ranked']:>3} would reach the model  e.g. {'; '.join(r.get('top', [])[:2])}")
    print("\nwork/scout-compare.json has every company, its board and its numbers.")


if __name__ == "__main__":
    main(sys.argv[1:])
