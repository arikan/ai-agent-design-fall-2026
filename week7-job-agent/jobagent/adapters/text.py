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


_N = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
_SEP = r"\s*(?:-|–|—|to)\s*"
_NUM = r"\$\s?" + _N
_RANGE = re.compile(_NUM + _SEP + r"\$?\s?" + _N)
# The same range with a currency code instead of a dollar sign: "130,000 to 190,000 USD", "USD 130,000 - 190,000".
_CODE = r"(?:USD|US\$|US dollars)"
_RANGE_CODE_AFTER = re.compile(_N + _SEP + _N + r"\s?" + _CODE)
_RANGE_CODE_BEFORE = re.compile(_CODE + r"\s?" + _N + _SEP + r"(?:" + _CODE + r"\s?)?" + _N)
_RANGES = (_RANGE, _RANGE_CODE_AFTER, _RANGE_CODE_BEFORE)
_PAY_WORDS = re.compile(r"(salary|pay|compensation|base|range|ote|annual|per year|/yr|usd)", re.I)


def _value(num, k):
    v = float(num.replace(",", ""))
    if k:
        v *= 1000
    return int(v)


def _range(m):
    lo, hi = _value(m.group(1), m.group(2)), _value(m.group(3), m.group(4) or m.group(2))
    if lo < 1000 or hi < lo:          # hourly or garbled; leave it out rather than guess
        return None, None
    return lo, hi


def extract_range(text):
    """Pay range from a field that is known to be about pay, like '$120K – $150K' or '120,000 - 150,000 USD'."""
    for rx in _RANGES:
        m = rx.search(text or "")
        if m:
            return _range(m)
    return None, None


def pay_match(text):
    """The first pay range in free text, as a regex match: only accepted near a pay word, to avoid funding amounts."""
    found = []
    for rx in _RANGES:
        for m in rx.finditer(text or ""):
            window = text[max(0, m.start() - 80): m.end() + 40]
            if _PAY_WORDS.search(window) and _range(m)[0]:
                found.append(m)
                break
    return min(found, key=lambda m: m.start()) if found else None


def extract_from_text(text):
    """Pay range from free text: only accepted near a pay word, to avoid funding amounts."""
    m = pay_match(text)
    return _range(m) if m else (None, None)
