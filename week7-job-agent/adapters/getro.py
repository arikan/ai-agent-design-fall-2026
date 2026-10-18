"""Getro: portfolio job boards run by many VC firms (a Next.js site).
The page's build id leads to a JSON data route holding the first 20 jobs.
Getro listings carry no description, so the text is assembled from the
fields it does have; expect more unknown scores from these.
Config: domain (for example jobs.example-vc.com)
"""

import re
from datetime import datetime, timezone

from .base import BaseSource

BUILD = re.compile(r"_next/static/([A-Za-z0-9_-]+)/_buildManifest")


class Getro(BaseSource):
    @classmethod
    def domains(cls, config):
        return [config["domain"]]

    def fetch(self):
        base = f"https://{self.config['domain']}"
        m = BUILD.search(self.http.get(base))
        if not m:
            raise ValueError("no Next.js build id on the board page; the site may have changed")
        data = self.http.get_json(f"{base}/_next/data/{m.group(1)}/jobs.json")
        return data["pageProps"]["initialState"]["jobs"]["found"]

    def normalize(self, raw):
        org = raw.get("organization") or {}
        locs = raw.get("locations") or []
        skills = [s if isinstance(s, str) else s.get("name", "") for s in raw.get("skills") or []]
        text = " ".join(filter(None, [raw.get("title"), f"at {org.get('name')}" if org.get("name") else "",
                                      ("Skills: " + ", ".join(skills)) if skills else "",
                                      f"Work mode: {raw['workMode']}" if raw.get("workMode") else ""]))
        lo = int(raw["compensationAmountMinCents"]) // 100 if raw.get("compensationAmountMinCents") else None
        hi = int(raw["compensationAmountMaxCents"]) // 100 if raw.get("compensationAmountMaxCents") else None
        posted = datetime.fromtimestamp(int(raw["createdAt"]), timezone.utc).date().isoformat() if raw.get("createdAt") else None
        return self.posting(
            id=raw.get("id") or raw.get("slug"), title=raw.get("title"), company=org.get("name"),
            location=", ".join(locs) or ("Remote" if raw.get("workMode") == "remote" else ""), text=text,
            remote=raw.get("workMode") == "remote", pay_min=lo, pay_max=hi, posted=posted,
            url=raw.get("url") or f"https://{self.config['domain']}/jobs/{raw.get('slug') or raw.get('id')}")
