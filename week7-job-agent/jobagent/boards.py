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
