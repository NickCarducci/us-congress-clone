"""A state's code, section by section, so a section a state bill cites opens
as its text in the app instead of a link out.

    python3 export_state_code.py va <out dir>   -> <out>/t<title>.json.gz, <out>/release.json

Each title file: {"<section>": {"h": heading, "t": text}}.

Virginia: the General Assembly's Law Portal (law.lis.virginia.gov), its
published per-title CSV downloads (law-library page), titles listed by its
JSON web service. Statutory text only: the portal already leaves out what
Michie (Matthew Bender) holds copyright in, the annotations and revisors'
notes. One title at a time, a few seconds apart, once a week.
"""
import csv, gzip, html, io, json, os, re, sys, time, urllib.request

UA = {"User-Agent": "populist-state-code-export (weekly; one title at a time)"}
csv.field_size_limit(sys.maxsize)


def get(url, attempts=3):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))


def plain(body):
    """The portal's HTML body as text: one line per paragraph."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", body or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def virginia(out):
    base = "https://law.lis.virginia.gov"
    titles = json.loads(get(f"{base}/api/CoVTitlesGetListOfJson/"))
    count = 0
    for entry in titles:
        number = str(entry["TitleNumber"]).strip()
        if not re.fullmatch(r"\d+(\.\d+)?", number):
            continue
        raw = get(f"{base}/CSV/CoVTitle_{number}.csv").decode("utf-8-sig", "replace")
        sections = {}
        for row in csv.DictReader(io.StringIO(raw)):
            section = (row.get("Section") or "").strip()
            if not section:
                continue
            sections[section] = {"h": (row.get("Title") or "").strip(), "t": plain(row.get("Body"))}
        if not sections:
            sys.exit(f"title {number}: no sections (format changed?)")
        with gzip.open(os.path.join(out, f"t{number}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
        count += len(sections)
        print(f"t{number}\t{len(sections)}", flush=True)
        time.sleep(3)
    return {"source": f"{base}/law-library", "titles": len(titles), "sections": count}


STATES = {"va": virginia}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in STATES:
        sys.exit(__doc__)
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    meta = STATES[sys.argv[1]](out)
    meta["exportedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(out, "release.json"), "w") as f:
        json.dump(meta, f)
