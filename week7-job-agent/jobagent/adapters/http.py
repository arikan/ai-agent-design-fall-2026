"""A small HTTP client that only reaches a source's own domains.

This guard is a courtesy check inside the code. The real limit is the cloud
environment's network setting: domains not on its allowed list never connect,
whatever the code tries.

In test mode it replays saved responses instead of touching the network.
"""

import json
import time
import os
import ssl
import urllib.parse
import urllib.request

USER_AGENT = "CourseJobAgent/0.1 (course project; contact via github.com/arikan/ai-agent-design-fall-2026)"


class BlockedDomain(Exception):
    pass


class RobotsDisallowed(Exception):
    pass


_ROBOTS = {}


def robots_allows(url, ctx=None, timeout=8):
    """Whether the site's robots.txt lets automated readers fetch this page. Job board APIs are made for programs;
    web pages are made for people, and a site may ask programs to stay off some of them (search results, often).
    If robots.txt can't be read, the page is allowed."""
    import urllib.robotparser
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except Exception:
            rp = None
        _ROBOTS[base] = rp
    rp = _ROBOTS[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


class Http:
    def __init__(self, allowed, fixtures=None, timeout=20):
        self.allowed = [d.lower() for d in allowed]
        self.fixtures = fixtures
        self.timeout = timeout
        self.log = []
        cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        self.ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()

    def _check(self, url):
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in self.allowed):
            raise BlockedDomain(f"{host} is not one of this source's domains ({', '.join(self.allowed)})")

    def page(self, url):
        """A web page meant for people: fetched only if the site's robots.txt allows it."""
        if self.fixtures is None and not robots_allows(url, self.ctx):
            raise RobotsDisallowed(f"the site's robots.txt asks automated readers not to read {url}")
        return self.get(url, headers={"Accept": "text/html,*/*;q=0.5"})

    def _url(self, url, params):
        return url + ("?" + urllib.parse.urlencode(params) if params else "")

    def _send(self, method, url, body=None, headers=None):
        self._check(url)
        entry = {"method": method, "url": url}
        self.log.append(entry)
        if self.fixtures is not None:
            key = f"{method} {url}"
            if body is not None and isinstance(body, dict) and "variables" in body:
                key += " " + json.dumps(body["variables"], sort_keys=True)   # GraphQL: one URL, many queries
            if key not in self.fixtures:
                entry["status"] = "no fixture"
                raise KeyError(f"no saved response for {key}")
            entry["status"] = 200
            return self.fixtures[key]
        h = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                    entry["status"] = r.status
                    return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
            except urllib.error.HTTPError as e:
                entry["status"] = e.code
                # 429 Too Many Requests and 503 mean "slow down": wait as asked (at most 15 s), then try again, twice.
                if e.code in (429, 503) and attempt < 2:
                    try:
                        wait = min(float(e.headers.get("Retry-After") or 0), 15) or 5 * (attempt + 1)
                    except ValueError:
                        wait = 5 * (attempt + 1)
                    entry.setdefault("retries", []).append({"status": e.code, "waited": wait})
                    time.sleep(wait)
                    continue
                raise

    def get(self, url, params=None, headers=None):
        return self._send("GET", self._url(url, params), headers=headers)

    def get_json(self, url, params=None):
        return json.loads(self.get(url, params))

    def post_json(self, url, payload):
        return json.loads(self._send("POST", url, body=payload))
