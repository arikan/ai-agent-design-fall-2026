"""Greenhouse: public JSON API per company board, no key.
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Config: board_token, company_name, company_from_title (optional)

company_from_title is for boards that pool jobs from several companies under one board and
put the company in the title, like a16z's "Partner 18, IT Engineer". It is a regular
expression matched at the start of the title; its first group becomes part of the company
("a16z · Partner 18") and the match is removed from the title ("IT Engineer").
"""

import re

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
        title = raw.get("title") or ""
        company = self.config.get("company_name") or self.config["board_token"].replace("-", " ").title()
        pattern = self.config.get("company_from_title")
        m = re.match(pattern, title) if pattern else None
        if m and m.groups() and m.group(1):
            company, title = f"{company} · {m.group(1).strip()}", title[m.end():].strip(" ,-–—") or title
        return self.posting(
            id=raw.get("id"), title=title, location=loc, text=text, pay_min=lo, pay_max=hi,
            company=company,
            url=raw.get("absolute_url"), posted=raw.get("updated_at"),
            remote=any("remote" in (d.get("name") or "").lower() for d in raw.get("departments", [])))
