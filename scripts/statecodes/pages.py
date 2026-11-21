"""For codes published as web pages (a page per title or per chapter): the
units are links on an index page, and a page's sections are split at each
section's heading. A state on pages is then just its index, its link pattern
and its heading pattern.
"""
import re
from .crawl import get, plain

# Where a division heading begins, so the last section before it ends there.
DIVISION = r"<(?:p|div|h\d)[^>]*>\s*(?:<[^>]+>\s*)*(?:CHAPTER|SUBCHAPTER|PART|ARTICLE|TITLE|DIVISION)\s+[0-9A-Z]"


def links(index_url, pattern):
    """Each distinct first group of pattern on the index page, in page order."""
    page = get(index_url).decode("utf-8", "replace")
    seen = []
    for m in re.finditer(pattern, page):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def split_sections(page, head, drop=(), end=DIVISION):
    """{number: {"h", "t"}} from one page. head matches a section's opening, with
    groups num and (optionally) heading; its text runs to the next head, or to
    the next division heading (end). drop: patterns removed first."""
    for pattern in drop:
        page = re.sub(pattern, " ", page, flags=re.S)
    page = re.sub(r"\s+", " ", page)   # source line wraps aren't paragraphs; tags are
    heads = list(re.finditer(head, page, re.S))
    sections = {}
    for i, m in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(page)
        body = page[m.end():stop]
        if end:
            cut = re.search(end, body)
            body = body[:cut.start()] if cut else body
        text = plain(body)
        heading = plain(m.groupdict().get("heading") or "").rstrip(".")
        if not heading and text:
            heading, _, text = text.partition("\n")
        number = m.group("num").strip()
        if text and number not in sections:
            sections[number] = {"h": heading, "t": text}
    return sections
