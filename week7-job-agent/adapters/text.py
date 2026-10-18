"""Shared helpers: HTML to plain text, and pay ranges from text."""

import html
import re
from html.parser import HTMLParser

BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup, unescape_first=False):
    """Plain text from HTML. Greenhouse double encodes its HTML, hence unescape_first."""
    if not markup:
        return ""
    if unescape_first:
        markup = html.unescape(markup)
    p = _Text()
    p.feed(markup)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


_NUM = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
_RANGE = re.compile(_NUM + r"\s*(?:-|–|—|to)\s*" + r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?")
_PAY_WORDS = re.compile(r"(salary|pay|compensation|base|range|ote|annual|per year|/yr|usd)", re.I)


def _value(num, k):
    v = float(num.replace(",", ""))
    if k:
        v *= 1000
    return int(v)


def extract_range(text):
    """Pay range from a field that is known to be about pay, like '$120K – $150K'."""
    m = _RANGE.search(text or "")
    if not m:
        return None, None
    lo, hi = _value(m.group(1), m.group(2)), _value(m.group(3), m.group(4) or m.group(2))
    if lo < 1000 or hi < lo:          # hourly or garbled; leave it out rather than guess
        return None, None
    return lo, hi


def extract_from_text(text):
    """Pay range from free text: only accepted near a pay word, to avoid funding amounts."""
    for m in _RANGE.finditer(text or ""):
        window = text[max(0, m.start() - 80): m.end() + 40]
        if _PAY_WORDS.search(window):
            lo, hi = extract_range(m.group(0))
            if lo:
                return lo, hi
    return None, None
