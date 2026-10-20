"""Work out a source from any careers page address, so nobody has to fill in the advanced form.

  uv run jobagent figure <url> [--model <id>]   -> work/figure-result.json, and the source if one was found
  uv run jobagent figure <url> --model none     -> the code part only; the page's HTML goes to work/figure-page.html
                                                   for the cloud session to read (RUN.md, "Figure out a source")

Code first: a page that embeds a Greenhouse, Lever, Ashby or Workable board, or offers an RSS feed,
needs no model. Otherwise the model reads the page's HTML and proposes selectors for the web page
adapter; each proposal is tested with the real adapter, and what went wrong is fed back, up to three
times. The result says what it found and how, or that this page needs a person: JavaScript-only
pages, logins, and some applicant-tracking systems can't be read from one address.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import model as llm
from . import sources
from .adapters.http import Http
from .adapters.text import html_to_text

WORK = Path(__file__).resolve().parents[1] / "work"
EMBEDS = [    # a page that loads a known board: the board's own API is the reliable source
    (r"boards\.greenhouse\.io/(?:embed/job_board\?for=|)([A-Za-z0-9_-]+)", "greenhouse", "board_token"),
    (r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)", "greenhouse", "board_token"),
    (r"jobs\.lever\.co/([A-Za-z0-9_-]+)", "lever", "company"),
    (r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)", "ashby", "company"),
    (r"apply\.workable\.com/([A-Za-z0-9_-]+)", "workable", "account"),
]
SKIP_SLUGS = {"embed", "jobs", "api", "job", "careers", "en", "en-us", "v1"}


def fetch_page(url):
    host = urlparse(url).hostname
    return Http([host], timeout=25).get(url, headers={"Accept": "text/html,*/*;q=0.5"})


def company_from(url):
    host = (urlparse(url).hostname or "").lower()
    parts = [p for p in host.split(".") if p not in ("www", "jobs", "careers", "boards", "apply", "com", "org", "net", "io", "co", "xyz", "ai")]
    return (parts[-1] if parts else host).replace("-", " ").title()


def by_code(url, html):
    """Known boards embedded in the page, then an RSS link."""
    for rx, adapter, key in EMBEDS:
        for slug in re.findall(rx, html):
            if slug.lower() not in SKIP_SLUGS:
                return {"id": f"{adapter}:{slug}", "adapter": adapter, "enabled": True, "category": "", "cap": 1000, "note": f"Found on {url}",
                        "config": {key: slug, "company_name": company_from(url)}}, f"the page loads a {adapter} board"
    m = re.search(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', html, re.I) or \
        re.search(r'<link[^>]+href="([^"]+)"[^>]+type="application/(?:rss|atom)\+xml"', html, re.I)
    if m:
        feed = urljoin(url, m.group(1))
        return {"id": f"rss:{urlparse(url).hostname}", "adapter": "rss", "enabled": True, "category": "", "cap": 1000, "note": f"Feed found on {url}",
                "config": {"url": feed, "company_name": company_from(url)}}, "the page offers an RSS feed"
    return None, None


def trim_html(html, limit=60000):
    """The page without scripts, styles and SVG, so the model sees the structure that selectors need."""
    h = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", html)
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"[ \t]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    if len(h) > limit:      # keep the middle too: job lists often sit after a long header
        h = h[: limit * 2 // 3] + "\n…\n" + h[-limit // 3:]
    return h


def by_model(url, html, model=None, log=print):
    system = ("You set up a job-board reader. Given a careers page's HTML, answer with JSON only: "
              '{"selectors": {"job_card": "<css>", "title": "<css>", "location": "<css or empty>", "company": "<css or empty>", "link": "<css, default a>"}, '
              '"detail_text": "<css on each job page for its description, or empty>", "company_name": "<name>", "note": "<one line: what the page is>"} '
              "or, if the page shows no job listings in its HTML (they load with JavaScript, or it is a search form), "
              '{"impossible": "<one plain sentence why, and where the jobs really come from if you can tell>"}. '
              "Selectors are CSS, for BeautifulSoup. job_card matches one element per job; title and the others are searched inside it.")
    page = trim_html(html)
    attempts, tried = [], []
    for n in range(3):
        user = f"Page: {url}\n\n" + (f"Earlier attempts and what happened:\n{json.dumps(attempts, indent=1)}\n\n" if attempts else "") + f"HTML:\n{page}"
        log(f"figure: asking {llm.chosen(model)} for selectors, attempt {n + 1}")
        text, u = llm.complete(system, user, model)
        try:
            ans = llm.json_block(text)
        except (ValueError, json.JSONDecodeError):
            attempts.append({"answer": text[:300], "result": "not JSON"})
            continue
        if ans.get("impossible"):
            return None, ans["impossible"], tried
        sel = ans.get("selectors") or {}
        src = {"id": f"html:{urlparse(url).hostname}", "adapter": "html_scraper", "enabled": True, "category": "", "cap": 1000,
               "note": (ans.get("note") or "")[:160],
               "config": {"url": url, "selectors": {k: v for k, v in sel.items() if v}, "company_name": ans.get("company_name") or company_from(url),
                          **({"detail_text": ans["detail_text"]} if ans.get("detail_text") else {})}}
        postings, h = sources.run_source(src)
        tried.append({"selectors": src["config"]["selectors"], "status": h["status"], "kept": h.get("kept", 0), "error": h.get("error")})
        if h["status"] == "ok" and h.get("kept", 0) > 0:
            return src, f"selectors proposed by {u.get('model') or llm.chosen(model)} and checked: {h['kept']} posts", tried
        attempts.append({"selectors": sel, "result": h.get("error") or f"{h['status']}, {h.get('kept', 0)} posts kept",
                         "titles_seen": [p["title"] for p in postings[:3]]})
    return None, "no selectors found that read this page", tried


def figure(url, model=None, log=print):
    result = {"url": url, "source": None, "how": None, "tried": []}
    try:
        html = fetch_page(url)
    except Exception as e:
        result["how"] = f"could not open the page: {type(e).__name__}: {e}"[:300]
        return result
    src, how = by_code(url, html)
    if src:
        postings, h = sources.run_source(src)
        if h["status"] == "ok" and h.get("kept", 0):
            result.update(source=src, how=f"{how}, {h['kept']} posts")
            return result
        result["tried"].append({"source": src["id"], "status": h["status"], "error": h.get("error")})
    if len(html_to_text(html)) < 200:
        result["how"] = "the page is empty without JavaScript, so its jobs can't be read from this address"
        return result
    if model == "none":        # the cloud session is the model: it reads work/figure-page.html itself
        (WORK / "figure-page.html").write_text(trim_html(html))
        result["how"] = "needs a model: the trimmed page is in work/figure-page.html"
        return result
    try:
        src, how, tried = by_model(url, html, model, log)
    except SystemExit as e:        # the model couldn't be reached or isn't set up
        result["how"] = f"the model step failed: {e}"[:300]
        return result
    result["tried"] += tried
    result.update(source=src, how=how)
    return result


def main(argv):
    m = argv[argv.index("--model") + 1] if "--model" in argv and len(argv) > argv.index("--model") + 1 else None
    url = next((a for a in argv if a.startswith("http")), None)
    if not url:
        sys.exit(__doc__)
    r = figure(url, m)
    WORK.mkdir(exist_ok=True)
    (WORK / "figure-result.json").write_text(json.dumps(r, indent=1))
    print(json.dumps({"source": (r["source"] or {}).get("id"), "how": r["how"]}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
