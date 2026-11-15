"""State bill text, the state counterpart of bill-text-watcher.yml: each
scraped bill's latest version, as text, for "How does this affect me?".

    python3 fetch_state_texts.py <scrape dir(s), e.g. scrape/nj or scrape/paupper,scrape/palower> <out-dir>
        [--rpm 60] [--deadline 19800]

Reads the Open States bill files (bill_*.json, "versions" with links), picks
each bill's latest version (HTML preferred, else PDF via pdftotext), and writes
<out-dir>/<sha1 of the url>.txt plus <out-dir>/index.json:
{"<session>|<identifier>": {"file", "url", "note", "fetched"}}. A document
already fetched (same url, so the same version) is skipped; bills with the
newest activity go first; at --deadline seconds it stops and the next run
continues. Requests to the legislature are paced at --rpm.
"""
import argparse
import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

UA = "populist-state-bills/1.0"


def latest_version(bill):
    """(url, note, kind) of a bill's latest version, HTML link preferred."""
    versions = [v for v in bill.get("versions") or [] if v.get("links")]
    if not versions:
        return None
    version = sorted(versions, key=lambda v: str(v.get("date") or ""))[-1] if any(v.get("date") for v in versions) else versions[-1]
    links = version["links"]
    for kind in ("text/html", "application/pdf"):
        for link in links:
            if (link.get("media_type") or "").startswith(kind):
                return link["url"], version.get("note"), kind
    return links[0]["url"], version.get("note"), links[0].get("media_type") or ""


def last_action(bill):
    return max((str(a.get("date") or "") for a in bill.get("actions") or []), default="")


def html_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def pdf_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        result = subprocess.run(["pdftotext", "-layout", handle.name, "-"], capture_output=True, timeout=120)
    return result.stdout.decode("utf-8", "replace").strip()


def decode(data, content_type=""):
    """The page's declared charset, else UTF-8, else Windows-1252 (NJ's pages)."""
    declared = re.search(r"charset=([\w-]+)", content_type or "") or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4000], re.I)
    names = [declared.group(1).decode() if isinstance(declared.group(1), bytes) else declared.group(1)] if declared else []
    for name in names + ["utf-8", "cp1252"]:
        try:
            return data.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def document_text(url, kind, fetch):
    data, content_type = fetch(url)
    if "pdf" in (content_type or kind) or data[:4] == b"%PDF":
        return pdf_text(data)
    return html_text(decode(data, content_type))


def http_fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(), response.headers.get("Content-Type", "")


def main(argv=None, fetch=http_fetch, now=time.time, sleep=time.sleep):
    parser = argparse.ArgumentParser()
    parser.add_argument("scrape")
    parser.add_argument("out")
    parser.add_argument("--rpm", type=float, default=60)
    parser.add_argument("--deadline", type=float, default=19800)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    index_path = os.path.join(args.out, "index.json")
    try:
        index = json.load(open(index_path))
    except (OSError, ValueError):
        index = {}
    bills = []
    for folder in args.scrape.split(","):
        for path in glob.glob(os.path.join(folder, "bill_*.json")):
            try:
                bills.append(json.load(open(path)))
            except ValueError:
                continue
    bills.sort(key=last_action, reverse=True)
    start, wait = now(), 60.0 / max(args.rpm, 0.1)
    fetched = skipped = failed = 0
    for bill in bills:
        if now() - start > args.deadline:
            break
        found = latest_version(bill)
        if not found:
            continue
        url, note, kind = found
        key = f"{bill.get('legislative_session')}|{bill.get('identifier')}"
        name = hashlib.sha1(url.encode()).hexdigest() + ".txt"
        # The index says what's already on the server (the runner only has the index).
        if index.get(key, {}).get("url") == url:
            skipped += 1
            continue
        try:
            text = document_text(url, kind, fetch)
        except Exception as error:
            failed += 1
            print(f"warning: {key}: {error}", file=sys.stderr)
            sleep(wait)
            continue
        if text:
            with open(os.path.join(args.out, name), "w") as handle:
                handle.write(text)
            index[key] = {"file": name, "url": url, "note": note, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            fetched += 1
        sleep(wait)
        if fetched and fetched % 200 == 0:
            json.dump(index, open(index_path, "w"))
    json.dump(index, open(index_path, "w"))
    print(f"texts: {fetched} new, {skipped} unchanged, {failed} failed, {len(index)} in all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
