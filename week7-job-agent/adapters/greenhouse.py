"""Greenhouse: public JSON API per company board, no key.
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Config: board_token, company_name
"""

from .base import BaseSource
from .text import extract_from_text, html_to_text


class Greenhouse(BaseSource):
    API = "https://boards-api.greenhouse.io/v1/boards"

    @classmethod
    def domains(cls, config):
        return ["boards-api.greenhouse.io"]

    def fetch(self):
        data = self.http.get_json(f"{self.API}/{self.config['board_token']}/jobs", {"content": "true"})
        return data.get("jobs", [])

    def normalize(self, raw):
        # The singular `location` is the posting's own; `offices` collapses multi city postings.
        loc = (raw.get("location") or {}).get("name") or ", ".join(o["name"] for o in raw.get("offices", []) if o.get("name"))
        text = html_to_text(raw.get("content", ""), unescape_first=True)
        lo, hi = extract_from_text(text)
        return self.posting(
            id=raw.get("id"), title=raw.get("title"), location=loc, text=text, pay_min=lo, pay_max=hi,
            company=self.config.get("company_name") or self.config["board_token"].replace("-", " ").title(),
            url=raw.get("absolute_url"), posted=raw.get("updated_at"),
            remote=any("remote" in (d.get("name") or "").lower() for d in raw.get("departments", [])))
