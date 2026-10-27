"""The adapter contract.

Every adapter turns one kind of job source into postings in the same shape:
  fetch()          -> list of raw records, exactly as the source returns them
  normalize(raw)   -> one posting dict (see POSTING_FIELDS)

Generic adapters are config driven: one Greenhouse adapter serves every
Greenhouse board, with the board token in the source's config.
"""

POSTING_FIELDS = ["id", "company", "title", "location", "remote", "pay_min", "pay_max",
                  "industry", "url", "text", "posted"]
REQUIRED = ["company", "title", "location", "text"]


def safe_id(raw):
    """A posting's own id, usable as a database document id and a file name: letters, digits and _ . ~ : @ + -.
    Board ids (numbers, uuids) pass unchanged; a web page's id is its address, so the scheme and host are dropped,
    other characters become dashes, and a long one is shortened with a hash so it stays unique."""
    import hashlib
    import re
    from urllib.parse import urlparse
    raw = str(raw)
    s = raw
    if re.match(r"https?://", s):
        u = urlparse(s)
        s = u.path + ("?" + u.query if u.query else "")
    s = re.sub(r"[^A-Za-z0-9_.~:@+-]+", "-", s).strip("-") or hashlib.sha1(raw.encode()).hexdigest()[:12]
    if len(s) > 80:
        s = s[:60].rstrip("-") + "-" + hashlib.sha1(raw.encode()).hexdigest()[:10]
    return s


class BaseSource:
    # Domains this adapter may reach. Subclasses return them from config.
    def __init__(self, name, config, http):
        self.name = name
        self.config = config or {}
        self.http = http

    @classmethod
    def domains(cls, config):
        return []

    def fetch(self):
        raise NotImplementedError

    def normalize(self, raw):
        raise NotImplementedError

    def posting(self, **fields):
        p = {k: fields.get(k) for k in POSTING_FIELDS}
        p["remote"] = bool(p["remote"]) or "remote" in str(p["location"] or "").lower()
        p["industry"] = p["industry"] or self.config.get("industry")
        p["id"] = f"{self.name}:{safe_id(p['id'])}" if p["id"] is not None else None
        return p

    def run(self, cap):
        """Fetch, normalize and validate. Never raises: failures go into health."""
        health = {"source": self.name, "status": "ok", "fetched": 0, "normalized": 0,
                  "rejected": 0, "kept": 0, "capped": 0, "error": None, "requests": self.http.log}
        try:
            raws = self.fetch()
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if "Tunnel connection failed: 403" in msg or "host_not_allowed" in msg:
                msg = ("Blocked by the cloud environment's network setting. Add "
                       + ", ".join(self.domains(self.config)) + " to its allowed domains.")
            health.update(status="failed", error=msg[:300], blocked_by_network="Blocked by" in msg)
            return [], health
        health["fetched"] = len(raws)
        postings, problems = [], {}
        for raw in raws:
            try:
                p = self.normalize(raw)
                missing = [f for f in REQUIRED if not str(p.get(f) or "").strip()]
                if missing:
                    raise ValueError("missing " + ", ".join(missing))
                postings.append(p)
            except Exception as e:
                key = str(e)[:80]
                problems[key] = problems.get(key, 0) + 1
        health["normalized"] = len(postings)
        health["rejected"] = len(raws) - len(postings)
        if problems:
            health["rejections"] = problems
        kept = postings[:cap]
        health["kept"], health["capped"] = len(kept), len(postings) - len(kept)
        if not kept:
            health["status"] = "empty"
        return kept, health
