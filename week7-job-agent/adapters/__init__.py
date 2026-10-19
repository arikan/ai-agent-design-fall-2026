"""Adapter registry. A source names its adapter; this maps names to code.

Built in types live in this folder. A student's own adapter arrives as code
text in the source's config (adapter "custom"): it must define a class named
Adapter that subclasses BaseSource, and declare its domains in config.
"""

from .ashby import Ashby
from .base import BaseSource
from .getro import Getro
from .greenhouse import Greenhouse
from .html_scraper import HtmlScraper
from .json_api import JsonApi, dig
from .lever import Lever
from .rss import Rss
from .text import extract_from_text, extract_range, html_to_text
from .workable import Workable

TYPES = {"greenhouse": Greenhouse, "lever": Lever, "ashby": Ashby, "getro": Getro,
         "json_api": JsonApi, "html_scraper": HtmlScraper, "rss": Rss, "workable": Workable}

# Not fetched by code: the frozen corpus is read from disk, manual sources are reminders.
NON_FETCHING = {"corpus", "manual"}


def load_custom(code):
    ns = {"BaseSource": BaseSource, "html_to_text": html_to_text, "extract_range": extract_range,
          "extract_from_text": extract_from_text, "dig": dig}
    exec(compile(code, "<custom adapter>", "exec"), ns)
    cls = ns.get("Adapter")
    if not (isinstance(cls, type) and issubclass(cls, BaseSource)):
        raise ValueError("custom adapter code must define: class Adapter(BaseSource)")
    return cls


def adapter_class(source):
    if source["adapter"] == "custom":
        cls = load_custom(source["config"]["code"])
        declared = source["config"].get("domains", [])
        cls.domains = classmethod(lambda c, config, d=declared: d)
        return cls
    if source["adapter"] not in TYPES:
        raise ValueError(f"unknown adapter type: {source['adapter']}")
    return TYPES[source["adapter"]]


def domains_for(source):
    if source["adapter"] in NON_FETCHING:
        return []
    try:
        return [d for d in adapter_class(source).domains(source.get("config", {})) if d]
    except Exception:
        return []
