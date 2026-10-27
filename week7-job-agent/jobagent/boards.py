"""Find a company's job board by its name: the four board types that have a public API by company slug.

Used by the page's Add source (on this computer) and by suggestions that add sources."""

import json
import threading

BOARDS = {   # where a company's board lives, by its slug, and the public API that says whether it exists
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", "jobs"),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", None),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}", "jobs"),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{slug}", "jobs"),
}


def probe(name):
    """Which job boards a company name finds: tries each board type with the name as a slug."""
    import re
    import urllib.request
    slugs = []
    for s in (re.sub(r"[^a-z0-9]+", "", name.lower()), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")):
        if s and s not in slugs:
            slugs.append(s)
    found, lock = [], threading.Lock()

    def check(adapter, slug):
        url, key = BOARDS[adapter]
        try:
            req = urllib.request.Request(url.format(slug=slug), headers={"user-agent": "jobagent/0.2 (board check)"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            items = data.get(key) if key else data
            n = len(items) if isinstance(items, list) else None
            if n:
                with lock:
                    found.append({"adapter": adapter, "slug": slug, "jobs": n})
        except Exception:
            pass

    threads = [threading.Thread(target=check, args=(a, s)) for a in BOARDS for s in slugs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return sorted(found, key=lambda x: -x["jobs"])


def board_yield(name, search, have=(), floor=0.3, already=()):
    """Look up a company's board by name and measure it against a search, the way a run would:
    jobs listed, how many pass the search's filters, and how many rank high enough for the model.
    Returns None when no board is found. Used by suggestions and by `jobagent scout`."""
    from . import engine, sources
    found = [f for f in probe(name) if f"{f['adapter']}:{f['slug']}" not in set(have)]
    if not found:
        return None
    f = found[0]
    key = {"greenhouse": "board_token", "lever": "company", "ashby": "company", "workable": "account"}[f["adapter"]]
    src = {"id": f"{f['adapter']}:{f['slug']}", "adapter": f["adapter"], "enabled": True, "cap": 1000,
           "config": {key: f["slug"], "company_name": name}}
    try:
        postings, h = sources.run_source(src)
    except Exception as e:
        postings, h = [], {"status": "failed", "error": f"{type(e).__name__}: {e}"[:200]}
    db = (search or {}).get("preferences", {}).get("deal_breakers", {})
    passed = ranked = 0
    top = []
    if search and postings:
        for p in engine.normalize_and_dedupe(postings, []):
            if p["id"] in set(already):
                continue
            rp = engine.for_ranking(p)
            if engine.deal_breaker(rp, db):
                continue
            passed += 1
            sc = engine.prefilter_score(search, rp)
            if sc >= floor:
                ranked += 1
                top.append((sc, p["title"]))
    top.sort(reverse=True)
    return {**f, "id": src["id"], "status": h.get("status"), "listed": len(postings), "passed": passed, "ranked": ranked,
            "top": [t for _, t in top[:3]]}
