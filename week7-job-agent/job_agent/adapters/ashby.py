"""Ashby: public job posting API, no key. One request returns the whole board,
descriptions and pay included.
  GET https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
Config: company (the board name in the Ashby URL, jobs.ashbyhq.com/<company>), company_name
"""

from .base import BaseSource
from .text import extract_from_text, extract_range, html_to_text


class Ashby(BaseSource):
    API = "https://api.ashbyhq.com/posting-api/job-board"

    @classmethod
    def domains(cls, config):
        return ["api.ashbyhq.com"]

    def fetch(self):
        data = self.http.get_json(f"{self.API}/{self.config['company']}", {"includeCompensation": "true"})
        return [j for j in data.get("jobs", []) if j.get("isListed", True)]

    def normalize(self, raw):
        text = (raw.get("descriptionPlain") or "").strip() or html_to_text(raw.get("descriptionHtml", ""))
        comp = raw.get("compensation") or {}
        salary = next((c for c in comp.get("summaryComponents") or [] if (c.get("compensationType") or "").lower() == "salary"), None)
        lo, hi = (salary.get("minValue"), salary.get("maxValue")) if salary else (None, None)
        if lo is None and hi is None:
            lo, hi = extract_range(comp.get("compensationTierSummary") or "")
        if lo is None and hi is None:
            lo, hi = extract_from_text(text)
        places = [raw.get("location") or ""] + [s.get("location") or "" for s in raw.get("secondaryLocations") or []]
        org = self.config["company"]
        return self.posting(
            id=raw.get("id"), title=raw.get("title"), location=" | ".join(p for p in places if p), text=text,
            company=self.config.get("company_name") or org.replace("-", " ").title(),
            pay_min=lo, pay_max=hi, url=raw.get("jobUrl") or f"https://jobs.ashbyhq.com/{org}/{raw.get('id')}",
            posted=raw.get("publishedAt"),
            remote=bool(raw.get("isRemote")) or (raw.get("workplaceType") or "").lower() == "remote")
