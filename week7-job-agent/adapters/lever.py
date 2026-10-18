"""Lever: public JSON API per company, no key.
  GET https://api.lever.co/v0/postings/{company}?mode=json
Config: company, company_name
"""

from datetime import datetime, timezone

from .base import BaseSource
from .text import extract_from_text, html_to_text


class Lever(BaseSource):
    API = "https://api.lever.co/v0/postings"

    @classmethod
    def domains(cls, config):
        return ["api.lever.co"]

    def fetch(self):
        return self.http.get_json(f"{self.API}/{self.config['company']}", {"mode": "json"})

    def normalize(self, raw):
        cats = raw.get("categories") or {}
        parts = [raw.get("descriptionPlain") or html_to_text(raw.get("description", ""))]
        for section in raw.get("lists", []):
            parts.append(section.get("text", ""))
            parts.append(html_to_text(section.get("content", "")))
        text = "\n\n".join(p for p in parts if p).strip()
        sr = raw.get("salaryRange") or {}
        lo, hi = (int(sr["min"]), int(sr["max"])) if sr.get("min") and sr.get("max") else extract_from_text(text)
        posted = None
        if raw.get("createdAt"):
            posted = datetime.fromtimestamp(raw["createdAt"] / 1000, timezone.utc).date().isoformat()
        return self.posting(
            id=raw.get("id"), title=raw.get("text"), location=cats.get("location", ""), text=text,
            company=self.config.get("company_name") or self.config["company"].replace("-", " ").title(),
            pay_min=lo, pay_max=hi, url=raw.get("hostedUrl"), posted=posted,
            remote=(raw.get("workplaceType") == "remote"))
