"""Any server rendered careers page, read with CSS selectors. Fixed by editing selectors.
Config:
  url        the listing page
  selectors  {"job_card": "li.job-row", "title": ".title", "company": ".company",
              "link": "a", "location": ".location"}
  company_name  used when cards carry no company
  detail_text   optional selector; when set, each posting's own page is fetched
                (up to the source's cap) and this element's text becomes the posting text

Pages that build their content with JavaScript come back empty here; that is a
reason to look for the site's API, not to add more selectors. Needs beautifulsoup4.
"""

from urllib.parse import urljoin, urlparse

from .base import BaseSource


class HtmlScraper(BaseSource):
    @classmethod
    def domains(cls, config):
        return [urlparse(config["url"]).hostname]

    def fetch(self):
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise RuntimeError("beautifulsoup4 is not installed (pip install beautifulsoup4)") from e
        sel = self.config.get("selectors", {})
        if not sel.get("job_card"):
            raise ValueError("no job_card selector")
        soup = BeautifulSoup(self.http.get(self.config["url"]), "html.parser")
        cards = soup.select(sel["job_card"])
        if not cards:
            raise ValueError(f"job_card selector '{sel['job_card']}' matched nothing; the page may have changed or need JavaScript")
        jobs = []
        for card in cards:
            pick = lambda key: (card.select_one(sel[key]).get_text(" ", strip=True)
                                if sel.get(key) and card.select_one(sel[key]) else None)
            link = card.select_one(sel.get("link", "a"))
            job = {"title": pick("title"), "company": pick("company"), "location": pick("location"),
                   "url": urljoin(self.config["url"], link["href"]) if link and link.get("href") else None,
                   "card_text": card.get_text(" ", strip=True)}
            if job["title"]:
                jobs.append(job)
        if self.config.get("detail_text"):
            for job in jobs[: int(self.config.get("max_details", 20))]:
                if job["url"]:
                    try:
                        page = BeautifulSoup(self.http.get(job["url"]), "html.parser").select_one(self.config["detail_text"])
                        job["detail"] = page.get_text("\n", strip=True) if page else None
                    except Exception:
                        pass
        return jobs

    def normalize(self, raw):
        return self.posting(
            id=raw.get("url") or raw["title"], title=raw["title"], url=raw.get("url"),
            company=raw.get("company") or self.config.get("company_name"),
            location=raw.get("location") or self.config.get("default_location", ""),
            text=raw.get("detail") or raw.get("card_text"))
