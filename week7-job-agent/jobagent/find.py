"""Find a company's job board from its name, so adding a source can start from a name.

  uv run jobagent find "<company>" [--model <id>]   -> work/find-result.json, and the source if one was found
  uv run jobagent find "<company>" --model none     -> code only; if nothing is found, the cloud session searches
                                                       the web for the careers page (RUN.md, "Find a board by name")

In order, cheapest first:
1. The four board types with a public API by company slug (Greenhouse, Lever, Ashby, Workable): try the name as a slug.
2. The company's own site: try a few likely careers addresses (example.com/careers, /jobs, careers.example.com) and
   look for an embedded board or a feed in each page, as `jobagent figure` does.
3. With a model: read the careers page found in 2 and propose selectors, each tested (figure.py).
The result says what it found and how, or that it needs a careers page address from the person.
"""

import json
import re
import sys
from pathlib import Path

from . import boards, figure, sources

WORK = Path(__file__).resolve().parents[1] / "work"
TLDS = ("com", "ai", "io", "co")
MAX_TRIES = 14
PATHS = ("/careers", "/jobs", "/careers/", "")
LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workable": "Workable"}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def board_source(adapter, s, name):
    key = {"greenhouse": "board_token", "lever": "company", "ashby": "company", "workable": "account"}[adapter]
    return {"id": f"{adapter}:{s}", "adapter": adapter, "enabled": True, "category": "", "about": "", "cap": 1000,
            "note": "", "config": {key: s, "company_name": name}}


def candidates(name):
    """Likely careers addresses, grouped by domain: the first domain that answers is the company's."""
    s = slug(name)
    for tld in TLDS:
        yield [f"https://www.{s}.{tld}{p}" for p in PATHS] + [f"https://careers.{s}.{tld}", f"https://jobs.{s}.{tld}"]


def fetch(url):
    from urllib.parse import urlparse
    from .adapters.http import Http
    return Http([urlparse(url).hostname], timeout=8).get(url, headers={"Accept": "text/html,*/*;q=0.5"})


def find(name, model=None, log=print):
    name = name.strip()
    key = "name:" + name
    out = {"url": key, "name": name, "source": None, "how": None, "tried": []}
    log(f"find: looking for {name}'s job board")
    found = boards.probe(name)
    for f in found:
        src = board_source(f["adapter"], f["slug"], name)
        postings, h = sources.run_source(src)
        if h["status"] == "ok" and h.get("kept"):
            out.update(source=src, how=f"found {name}'s {LABEL[f['adapter']]} board, {h['kept']} posts")
            out["others"] = [f"{g['adapter']}:{g['slug']}" for g in found if g is not f]
            return out
        out["tried"].append({"source": src["id"], "status": h["status"], "error": h.get("error")})
    log("find: no Greenhouse, Lever, Ashby or Workable board under that name; trying the company's own site")
    page, tries = None, 0
    for group in candidates(name):
        answered = False
        for url in group:
            if tries >= MAX_TRIES:
                break
            tries += 1
            try:
                html = fetch(url)
            except Exception as e:
                out["tried"].append({"url": url, "error": type(e).__name__})
                continue
            answered = True
            src, how = figure.by_code(url, html)
            if src:
                src["config"]["company_name"] = name
                postings, h = sources.run_source(src)
                if h["status"] == "ok" and h.get("kept"):
                    out.update(source=src, how=f"{how} at {url}, {h['kept']} posts")
                    return out
            if page is None and len(figure.html_to_text(html)) > 200:
                page = url
        if answered or tries >= MAX_TRIES:     # this domain is the company's, or we've tried enough
            break
    if page and model != "none":
        log(f"find: reading {page}")
        r = figure.figure(page, model, log)
        out["tried"] += r.get("tried", [])
        if r.get("source"):
            out.update(source=r["source"], how=f"read {page}: {r['how']}")
            return out
        if r.get("follow"):
            out["follow"] = r["follow"]
        out["how"] = f"Found {page} but couldn't read its jobs: {r['how']}"
        out["page"] = page
        return out
    out["page"] = page
    out["how"] = (f"It isn't on Greenhouse, Lever, Ashby or Workable under that name; {page} may be its careers page" if page
                  else "It isn't on Greenhouse, Lever, Ashby or Workable under that name, and no careers page answered at its likely addresses")
    return out


def main(argv):
    m = argv[argv.index("--model") + 1] if "--model" in argv and len(argv) > argv.index("--model") + 1 else None
    words = [a for i, a in enumerate(argv) if a != "--model" and (i == 0 or argv[i - 1] != "--model")]
    if not words:
        sys.exit(__doc__)
    r = find(" ".join(words), m)
    WORK.mkdir(exist_ok=True)
    (WORK / "find-result.json").write_text(json.dumps(r, indent=1))
    print(json.dumps({"source": (r["source"] or {}).get("id"), "how": r["how"], "page": r.get("page")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
