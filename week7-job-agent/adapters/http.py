"""A small HTTP client that only reaches a source's own domains.

This guard is a courtesy check inside the code. The real limit is the cloud
environment's network setting: domains not on its allowed list never connect,
whatever the code tries.

In test mode it replays saved responses instead of touching the network.
"""

import json
import os
import ssl
import urllib.parse
import urllib.request

USER_AGENT = "CourseJobAgent/0.1 (Parsons student project; contact via course repo)"


class BlockedDomain(Exception):
    pass


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
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                entry["status"] = r.status
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            entry["status"] = e.code
            raise

    def get(self, url, params=None, headers=None):
        return self._send("GET", self._url(url, params), headers=headers)

    def get_json(self, url, params=None):
        return json.loads(self.get(url, params))

    def post_json(self, url, payload):
        return json.loads(self._send("POST", url, body=payload))
