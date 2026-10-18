"""Any JSON API that returns a list of jobs. Fixed by editing config, not code.
Config:
  url          the endpoint
  items_path   where the list sits, as dots: "" for a bare list, "jobs", "data.items"
  fields       where each posting field sits in one item, as dots:
               {"title": "position", "company": "company", "location": "location",
                "url": "url", "text": "description", "pay_min": "salary_min",
                "pay_max": "salary_max", "id": "id", "posted": "date"}
  filter_words optional; keep only items whose title or text contains one of them
  company_name optional; used when items carry no company
"""

from urllib.parse import urlparse

from .base import BaseSource
from .text import html_to_text


def dig(obj, path):
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(obj, list):
            obj = obj[int(part)] if part.isdigit() and int(part) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


class JsonApi(BaseSource):
    @classmethod
    def domains(cls, config):
        return [urlparse(config["url"]).hostname]

    def fetch(self):
        items = dig(self.http.get_json(self.config["url"]), self.config.get("items_path", ""))
        if not isinstance(items, list):
            raise ValueError(f"items_path '{self.config.get('items_path', '')}' does not point to a list")
        f = self.config.get("fields", {})
        items = [i for i in items if isinstance(i, dict) and dig(i, f.get("title", "title"))]
        words = [w.lower() for w in self.config.get("filter_words", [])]
        if words:
            items = [i for i in items if any(w in f"{dig(i, f.get('title', 'title'))} {dig(i, f.get('text', 'description'))}".lower() for w in words)]
        return items

    def normalize(self, raw):
        f = self.config.get("fields", {})
        get = lambda k, default=None: dig(raw, f.get(k, default or k))
        num = lambda v: int(float(v)) if v not in (None, "", 0, "0") else None
        text = get("text", "description") or ""
        return self.posting(
            id=get("id"), title=get("title"), company=get("company") or self.config.get("company_name"),
            location=get("location") or "", text=html_to_text(text) if "<" in str(text) else text,
            pay_min=num(get("pay_min")), pay_max=num(get("pay_max")), url=get("url"), posted=get("posted"),
            remote=bool(get("remote")) if f.get("remote") else False)
