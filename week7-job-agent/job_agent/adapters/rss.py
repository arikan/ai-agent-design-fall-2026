"""RSS or Atom job feeds.
Config: url, company_name (when items carry no company), default_location
"""

import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from .base import BaseSource
from .text import extract_from_text, html_to_text

ATOM = "{http://www.w3.org/2005/Atom}"


class Rss(BaseSource):
    @classmethod
    def domains(cls, config):
        return [urlparse(config["url"]).hostname]

    def fetch(self):
        root = ET.fromstring(self.http.get(self.config["url"]))
        items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
        out = []
        for it in items:
            t = lambda tag: (it.findtext(tag) or it.findtext(ATOM + tag) or "").strip()
            link = t("link") or ((it.find(ATOM + "link").get("href") if it.find(ATOM + "link") is not None else ""))
            out.append({"title": t("title"), "link": link, "description": t("description") or t("summary") or t("content"),
                        "posted": t("pubDate") or t("updated"), "guid": t("guid") or t("id") or link})
        return out

    def normalize(self, raw):
        text = html_to_text(raw["description"])
        title, company = raw["title"], self.config.get("company_name")
        if not company and " at " in title:          # many feeds use "Role at Company"
            title, company = title.rsplit(" at ", 1)
        lo, hi = extract_from_text(text)
        return self.posting(id=raw["guid"], title=title, company=company, text=text or title,
                            location=self.config.get("default_location", ""), url=raw["link"],
                            posted=raw["posted"], pay_min=lo, pay_max=hi)
