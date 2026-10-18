"""Ashby: public GraphQL endpoint, no key.
  POST https://jobs.ashbyhq.com/api/non-user-graphql
The board query returns brief postings; description and pay need one detail
query per posting, so detail fetches stop at the source's cap.
Config: company (the board name in the Ashby URL), company_name
"""

import time

from .base import BaseSource
from .text import extract_from_text, extract_range, html_to_text


class Ashby(BaseSource):
    API = "https://jobs.ashbyhq.com/api/non-user-graphql"
    LIST = """query List($org: String!) {
      jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $org) {
        teams { id name } jobPostings { id title locationName teamId employmentType } } }"""
    DETAIL = """query Detail($org: String!, $jobPostingId: String!) {
      jobPosting(organizationHostedJobsPageName: $org, jobPostingId: $jobPostingId) {
        id descriptionHtml compensationTierSummary } }"""
    DELAY = 0.2   # stays under Ashby's per address rate limit

    @classmethod
    def domains(cls, config):
        return ["jobs.ashbyhq.com"]

    def fetch(self):
        org = self.config["company"]
        board = (self.http.post_json(self.API, {"query": self.LIST, "variables": {"org": org}}).get("data") or {}).get("jobBoard") or {}
        teams = {t["id"]: t["name"] for t in board.get("teams") or []}
        briefs = (board.get("jobPostings") or [])[: int(self.config.get("max_details", 50))]
        out = []
        for i, p in enumerate(briefs):
            merged = {**p, "_team": teams.get(p.get("teamId"), "")}
            try:
                d = self.http.post_json(self.API, {"query": self.DETAIL, "variables": {"org": org, "jobPostingId": p["id"]}})
                merged.update((d.get("data") or {}).get("jobPosting") or {})
            except Exception:
                pass   # keep the brief; normalize will reject it if text is missing
            out.append(merged)
            if self.http.fixtures is None and i < len(briefs) - 1:
                time.sleep(self.DELAY)
        return out

    def normalize(self, raw):
        text = html_to_text(raw.get("descriptionHtml", ""))
        lo, hi = extract_range(raw.get("compensationTierSummary") or "")
        if lo is None:
            lo, hi = extract_from_text(text)
        org = self.config["company"]
        return self.posting(
            id=raw.get("id"), title=raw.get("title"), location=raw.get("locationName") or "", text=text,
            company=self.config.get("company_name") or org.replace("-", " ").title(),
            pay_min=lo, pay_max=hi, url=f"https://jobs.ashbyhq.com/{org}/{raw.get('id')}")
