"""Workable: public careers widget API, no key. One request returns the whole board,
descriptions included.
  GET https://apply.workable.com/api/v1/widget/accounts/{account}?details=true
Config: account (the name in apply.workable.com/<account>), company_name
"""

from .base import BaseSource
from .text import extract_from_text, html_to_text


class Workable(BaseSource):
    API = "https://apply.workable.com/api/v1/widget/accounts"

    @classmethod
    def domains(cls, config):
        return ["apply.workable.com"]

    def fetch(self):
        data = self.http.get_json(f"{self.API}/{self.config['account']}", {"details": "true"})
        return data.get("jobs", [])

    def normalize(self, raw):
        text = html_to_text(raw.get("description") or "")
        lo, hi = extract_from_text(text)
        place = lambda l: ", ".join(x for x in (l.get("city"), l.get("region") or l.get("state"), l.get("country")) if x)
        places = [place(l) for l in raw.get("locations") or []] or [place(raw)]
        acct = self.config["account"]
        return self.posting(
            id=raw.get("shortcode") or raw.get("code"), title=raw.get("title"), location=" | ".join(p for p in places if p), text=text,
            company=self.config.get("company_name") or acct.replace("-", " ").title(),
            pay_min=lo, pay_max=hi, url=raw.get("url") or raw.get("shortlink"), posted=raw.get("published_on"),
            remote=bool(raw.get("telecommuting")))
