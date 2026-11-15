"""American Samoa Senate measures, from the Fono Senate's site (asfono.gov).

No other source covers American Samoa (Open States has no scraper or even
metadata for it, LegiScan no territories), so this writes Open States-shaped
bill_*.json files itself, the shape the app's catalog reads from every scrape.

    python3 as_fono.py <out-dir> [--session 39]

The site is Wix: each session's measures are a page (/391documents = 39th
Legislature, 1st session) whose CMS repeater is embedded in the page's JSON.
Every item has a measure type, session, date, title, summary, sponsor, a
progress line ("1st Reading complete, 07/15/2025. 2nd Reading, PASSED ...")
and the measure's number linked to its PDF. Field ids differ by page, so
fields are told apart by content. Only the Senate publishes its measures this
way; House bills appear nowhere until they become law.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import urllib.request

BASE = "https://www.asfono.gov"
UA = "populist-state-bills/1.0"
SESSION_PAGES = {"39": ["391documents", "392documents"]}   # Legislature -> its sessions' pages
TYPES = re.compile(r"^Senate (Bill|Resolution|Concurrent Resolution|Joint Resolution)s?$", re.I)
NUMBER = re.compile(r"\b(S[.,\s]*[BCJR][.,\s]*(?:R[.,\s]*)?)\s*No\.?\s*(\d+)\s*-\s*(\d+)", re.I)
DATE_LONG = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
DATE_SHORT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def items_from_page(page):
    """{item id: [(text, [pdf links]), ...]} from the page's embedded JSON."""
    items = {}
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                match = re.match(r"comp-[a-z0-9]+__([0-9a-f-]{36})$", key)
                if match:
                    blob = json.dumps(child)
                    texts = [json.loads('"' + t + '"') for t in re.findall(r'"(?:html|text)": "((?:[^"\\]|\\.)*)"', blob)]
                    text = " ".join(re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip() for t in texts).strip()
                    links = re.findall(r'https?://[^"\\\s]+\.pdf', blob)
                    if text or links:
                        items.setdefault(match.group(1), []).append((text, links))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for blob in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', page, re.S):
        try:
            walk(json.loads(blob))
        except ValueError:
            continue
    return items


SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


def headline(text):
    """"CONFIRMATION-DIRECTOR, DEPARTMENT OF PUBLIC WORKS." -> "Confirmation-Director, Department of Public Works"."""
    words = text.strip().rstrip(".").lower().split()
    out = []
    for i, word in enumerate(words):
        out.append(word if i and word in SMALL else "-".join(part[:1].upper() + part[1:] for part in word.split("-")))
    return " ".join(out)


def iso(match):
    month, day, year = (int(g) for g in match.groups())
    return datetime.date(year, month, day).isoformat()


def measure(fields, legislature, page_url):
    """One item's fields as an Open States bill, or None if it has no number."""
    record = {"type": None, "date": None, "title": None, "summary": None, "sponsor": None,
              "progress": None, "number": None, "pdf": None}
    for text, links in fields:
        if text.startswith("FONO Senate Progress Bar") or not text and not links:
            continue
        number = NUMBER.search(text)
        if number and record["number"] is None:
            prefix = re.sub(r"[^A-Z]", "", number.group(1).upper())
            record["number"] = f"{prefix} {int(number.group(2))}-{int(number.group(3))}"
            record["pdf"] = links[0] if links else None
        elif TYPES.match(text):
            record["type"] = text
        elif DATE_LONG.match(text):
            record["date"] = datetime.datetime.strptime(text, "%B %d, %Y").date().isoformat()
        elif text.startswith("Hon."):
            record["sponsor"] = text
        elif re.search(r"\bReading\b|\bPASSED\b|\bVote\b|Hearing", text, re.I) and DATE_SHORT.search(text):
            record["progress"] = text
        elif re.match(r"^Session \d+$", text):
            continue
        elif record["title"] is None and text.upper() == text and len(text) > 3:
            record["title"] = text
        elif record["summary"] is None and len(text) > 30:
            record["summary"] = text
    if not record["number"]:
        return None
    kind = (record["type"] or "").lower()
    actions = []
    if record["date"]:
        actions.append({"date": record["date"], "description": f"Filed: {record['type'] or 'Senate measure'}"})
    # "1st Reading complete, 09/08/2025. Hearing scheduled 09/11/2025. 2nd Reading Passed. Vote: ..."
    last = None
    for sentence in [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z0-9])", record["progress"] or "") if s.strip()]:
        found = DATE_SHORT.search(sentence)
        if found:
            last = iso(found)
            actions.append({"date": last, "description": sentence.rstrip(".")})
        elif last and actions:
            actions[-1]["description"] += f". {sentence.rstrip('.')}"
    # "Hon. Name (District #6, Maoputasi)" or "Hon. Name, District #7: Ituau 1."
    sponsor_text = record["sponsor"] or ""
    sponsor = re.split(r"\s*\(|,\s*District\b", sponsor_text)[0].strip()
    district = re.search(r"District\s*#?\s*(\d+)", sponsor_text)
    return {
        "identifier": record["number"],
        "title": headline(record["title"]) if record["title"] else record["number"],
        "legislative_session": legislature,
        "classification": ["resolution" if "resolution" in kind else "bill"],
        "from_organization": '~{"classification": "upper"}',
        "abstracts": [{"abstract": record["summary"], "note": "summary"}] if record["summary"] else [],
        "actions": [{**a, "organization_id": '~{"classification": "upper"}', "classification": []} for a in actions],
        "sponsorships": [{"name": sponsor, "classification": "primary", "entity_type": "person", "primary": True}] if sponsor else [],
        "sources": [{"url": page_url}],
        "versions": [{"note": record["number"], "links": [{"url": record["pdf"], "media_type": "application/pdf"}]}] if record["pdf"] else [],
        "subject": [],
        "extras": {"sponsor_district": district.group(1) if district else None},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--session", default="39")
    args = parser.parse_args()
    out = os.path.join(args.out, "as")
    os.makedirs(out, exist_ok=True)
    count = 0
    for page_name in SESSION_PAGES.get(args.session, []):
        url = f"{BASE}/{page_name}"
        for fields in items_from_page(fetch(url)).values():
            bill = measure(fields, args.session, url)
            if not bill:
                continue
            name = hashlib.sha1(f"{args.session}:{bill['identifier']}".encode()).hexdigest()[:16]
            with open(os.path.join(out, f"bill_{name}.json"), "w") as handle:
                json.dump(bill, handle)
            count += 1
            print(f"save bill {bill['identifier']} in {args.session}", flush=True)
    print(f"bill: {count}")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
