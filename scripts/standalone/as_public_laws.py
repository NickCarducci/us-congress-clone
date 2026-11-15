"""American Samoa's enacted public laws, from the Office of Samoan Affairs.

    python3 as_public_laws.py <out-dir> [--text]

The Office of Samoan Affairs (osas.as, a Wix site) lists every Legislature's
public laws (16th to the current) on its Public Laws index, one table per
Legislature: public law number, session, the Senate/House bill it came from,
the A.S.C.A. section it amends when given, the date approved, a summary, and
the law's PDF. A table's page only carries its first 12 rows; the rest load
from the site's CMS as a visitor pages through, so every row is read the way
the site's own "Next" button reads it: its public data API with the visitor
token the site hands every browser (one request a second). Should that ever
fail, a table falls back to the rows on its page. Writes
<out-dir>/as/public-laws.json, a list of
{publicLaw, legislature, session, bill, asca, approved, summary, pdf, textFile};
with --text, each law's PDF text (pdftotext) as <out-dir>/as/text/<P.L.>.txt,
the official text the app's reference resolution hands to ChatGPT.
No other source has these: Open States and LegiScan don't cover American Samoa.
"""
import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = "https://www.osas.as"
INDEX = f"{BASE}/services-2"
UA = "populist-state-bills/1.0"
ROW = re.compile(
    r"P\.L\. (\d{2})-(\d{1,3})\s+(\d+(?:st|nd|rd|th) (?:Regular|Special))\s+"
    r"((?:[HS]\.\s?[BJCR]\.(?:\s?R\.)?|[HS]\.?[BJ]\.?)\s*(?:No\.\s*)?\d{2}-\d{1,3})?\s*(.*?)\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4})")


def fetch(url, binary=False):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    return data if binary else data.decode("utf-8", "replace")


def page_text(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def legislature_pages(index):
    """[(legislature number, url)] from the Public Laws index."""
    pages = {}
    for href, label in re.findall(r'<a[^>]+href="(https://www\.osas\.as/[^"]+)"[^>]*>(.*?)</a>', index, re.S):
        match = re.search(r"(\d{2})(?:st|nd|rd|th) Legislature", page_text(label))
        if match:
            pages[int(match.group(1))] = href
    return sorted(pages.items())


def bill_number(text):
    """"H.B. 38-8" -> "HB 38-8"; "S.C.R. No. 38-2" -> "SCR 38-2"."""
    if not text:
        return None
    match = re.match(r"([HS][.\s]*[BJCR][.\s]*(?:R[.\s]*)?)(?:No\.\s*)?(\d{1,3})(?:\s*-\s*(\d{1,3}))?", text.strip())
    if not match:
        return None
    prefix = re.sub(r"[^A-Z]", "", match.group(1).upper())
    if match.group(3):
        return f"{prefix} {int(match.group(2))}-{int(match.group(3))}"
    return f"{prefix} {int(match.group(2))}"   # older Legislatures numbered bills without one


def laws_on_page(page, legislature, url):
    text = page_text(page)
    laws = []
    for m in ROW.finditer(text):
        laws.append({
            "publicLaw": f"P.L. {m.group(1)}-{int(m.group(2)):02d}",
            "legislature": int(m.group(1)),
            "session": m.group(3),
            "bill": bill_number(m.group(4)),
            "asca": m.group(5).strip() or None,
            "approved": datetime.datetime.strptime(m.group(6), "%B %d, %Y").date().isoformat(),
            "summary": None,
            "pdf": None,
            "source": url,
        })
    # Each law's PDF link follows its number in the page source.
    for law in laws:
        number = re.escape(law["publicLaw"]).replace(r"\-0", r"\-0?")
        at = re.search(number, page)
        if at:
            link = re.search(r'https?://[^"\\\s]+\.pdf', page[at.end():at.end() + 4000])
            law["pdf"] = link.group(0) if link else None
    return laws


def collections_on_page(page):
    """The page's CMS collections ({"id": "Import989"}, listed by id)."""
    return set(re.findall(r'"([A-Za-z0-9_-]+)":\{"id":"\1"', page))


def visitor_token():
    request = urllib.request.Request(f"{BASE}/_api/v2/dynamicmodel", headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        apps = json.load(response).get("apps", {})
    return [app["instance"] for app in apps.values() if app.get("instance")]


def collection_rows(collection, tokens):
    """Every row of a collection, page by page (None if no token reads it)."""
    for token in tokens:
        rows, cursor = [], None
        try:
            while True:
                paging = {"limit": 100, **({"cursor": cursor} if cursor else {})}
                body = json.dumps({"dataCollectionId": collection, "query": {"cursorPaging": paging}}).encode()
                request = urllib.request.Request(f"{BASE}/_api/cloud-data/v2/items/query", data=body, headers={
                    "User-Agent": UA, "Authorization": token, "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = json.load(response)
                rows += [item["data"] for item in result.get("dataItems", [])]
                cursor = (result.get("pagingMetadata", {}).get("cursors") or {}).get("next")
                time.sleep(1)
                if not cursor:
                    return rows
        except Exception:
            continue
    return None


def approved_date(text):
    """"January 27, 2023" or "September 27th, 1985" -> ISO date; "November, 1988" -> "1988-11"."""
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip())
    for pattern, shape in (("%B %d, %Y", "%Y-%m-%d"), ("%B %d %Y", "%Y-%m-%d"), ("%B, %Y", "%Y-%m"), ("%B %Y", "%Y-%m")):
        try:
            return datetime.datetime.strptime(text, pattern).strftime(shape)
        except ValueError:
            continue
    return text or None


def law_from_row(row, source):
    """A CMS row as a law; None if it has no public law number."""
    # Collections name their fields differently ("publicLawNo", "plNo",
    # "publicLawNo19th"; "senateHouseBillNo", "senateOrHouseBillNo").
    field = lambda *prefixes: next((v for k, v in row.items() if any(k.startswith(p) for p in prefixes) and v not in (None, "")), "")
    number = re.search(r"(\d{2})\s*-\s*(\d{1,3})", str(field("publicLawNo", "plNo")))
    if not number:
        return None
    document = str(row.get("document") or "")
    file_id = re.search(r"ugd/([0-9a-f]+_[0-9a-f]+\.pdf)", document)
    approved = approved_date(str(row.get("dateApproved") or ""))
    asca = row.get("aSCA")
    # A bare number is a Title ("17.0" -> "Title 17").
    asca = f"Title {int(asca)}" if isinstance(asca, (int, float)) else str(asca or "").strip() or None
    return {
        "publicLaw": f"P.L. {number.group(1)}-{int(number.group(2)):02d}",
        "legislature": int(number.group(1)),
        "session": str(row.get("session") or "").strip() or None,
        "bill": bill_number(str(field("senateHouseBillNo", "senateOrHouseBillNo"))),
        "asca": asca,
        "approved": approved,
        "summary": str(row.get("summary") or "").strip() or None,
        "pdf": f"{BASE}/_files/ugd/{file_id.group(1)}" if file_id else (row.get("url") or None),
        "source": source,
    }


def pdf_text(pdf_bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(pdf_bytes)
        handle.flush()
        result = subprocess.run(["pdftotext", "-layout", handle.name, "-"], capture_output=True, timeout=120)
    return result.stdout.decode("utf-8", "replace").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()
    out = os.path.join(args.out, "as")
    os.makedirs(os.path.join(out, "text"), exist_ok=True)
    tokens = visitor_token()
    by_number, read = {}, set()
    for legislature, url in legislature_pages(fetch(INDEX)):
        page = fetch(url)
        on_page = laws_on_page(page, legislature, url)
        for law in on_page:
            by_number.setdefault(law["publicLaw"], law)
        for collection in sorted(collections_on_page(page) - read):
            read.add(collection)
            rows = collection_rows(collection, tokens)
            if rows is None:
                print(f"warning: {collection}: the data API refused; its page rows only", file=sys.stderr)
                continue
            for row in rows:
                law = law_from_row(row, url)
                if law:
                    # The API's row is complete (summary, PDF); it wins over the page's.
                    old = by_number.get(law["publicLaw"], {})
                    by_number[law["publicLaw"]] = {**law, **{k: v for k, v in old.items() if v and not law.get(k)}}
        print(f"{legislature}th Legislature page read ({len(on_page)} rows on the page)", flush=True)
    laws = sorted(by_number.values(), key=lambda l: (l["legislature"], l["publicLaw"]))
    for legislature in sorted({l["legislature"] for l in laws}):
        print(f"{legislature}: {sum(1 for l in laws if l['legislature'] == legislature)} laws")
    for law in laws:
        law["textFile"] = None
        if args.text and law["pdf"]:
            name = law["publicLaw"].replace("P.L. ", "PL-") + ".txt"
            path = os.path.join(out, "text", name)
            if not os.path.exists(path):
                try:
                    text = pdf_text(fetch(law["pdf"], binary=True))
                except Exception as error:
                    print(f"warning: {law['publicLaw']}: {error}", file=sys.stderr)
                    continue
                if not text:
                    continue   # a scanned PDF with no text layer
                with open(path, "w") as handle:
                    handle.write(text)
            law["textFile"] = f"text/{name}"
    with open(os.path.join(out, "public-laws.json"), "w") as handle:
        json.dump(laws, handle, indent=1)
    print(f"laws: {len(laws)}, with text: {sum(1 for l in laws if l['textFile'])}")
    return 0 if laws else 1


if __name__ == "__main__":
    sys.exit(main())
