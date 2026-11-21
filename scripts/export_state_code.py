"""A state's code, section by section, so a section a state bill cites opens
as its text in the app instead of a link out.

    python3 export_state_code.py va <out dir>   -> <out>/t<title>.json.gz, <out>/release.json

Each title file: {"<section>": {"h": heading, "t": text}}.

Virginia: the General Assembly's Law Portal (law.lis.virginia.gov), its
published per-title CSV downloads (law-library page), titles listed by its
JSON web service. Statutory text only: the portal already leaves out what
Michie (Matthew Bender) holds copyright in, the annotations and revisors'
notes. One title at a time, a few seconds apart, once a week.

California: the Legislature's downloadable data (downloads.leginfo.legislature.ca.gov,
which leginfo asks bulk users to use instead of the site), the current
session's pubinfo_<year>.zip, rebuilt each Sunday: LAW_SECTION_TBL (one row
per section; its text in LAW_SECTION_TBL_<n>.lob, CAML XML) and CODES_TBL
(the codes' names). One download a week. Files are t<CODE>.json.gz ("PEN").
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


def california(out):
    import tempfile, zipfile
    site = "https://downloads.leginfo.legislature.ca.gov/"
    index = get(site).decode("utf-8", "replace")
    years = sorted(int(y) for y in re.findall(r'pubinfo_(\d{4})\.zip', index))
    if not years:
        sys.exit("no pubinfo_<year>.zip in the downloads index")
    url = f"{site}pubinfo_{years[-1]}.zip"
    unquote = lambda v: None if v in ("NULL", "") else v.strip("`")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pubinfo.zip")
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        with zipfile.ZipFile(path) as z:
            names = {}
            for line in z.read("CODES_TBL.dat").decode("utf-8", "replace").splitlines():
                cols = [unquote(c) for c in line.split("\t")]
                if len(cols) >= 2 and cols[0]:
                    names[cols[0]] = re.sub(r"\s+-\s+[A-Z]+$", "", cols[1] or cols[0])
            codes = {}   # code -> {section: (effective, entry)}
            with z.open("LAW_SECTION_TBL.dat") as f:
                for raw in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                    cols = [unquote(c) for c in raw.rstrip("\n").split("\t")]
                    if len(cols) < 16 or cols[15] != "Y":
                        continue
                    code, section, effective, history, lob = cols[1], (cols[2] or "").rstrip("."), cols[6] or "", cols[13], cols[14]
                    if not code or not section or not lob:
                        continue
                    try:
                        xml = z.read(lob).decode("utf-8", "replace")
                    except KeyError:
                        continue
                    text = plain(re.sub(r'<span class="EnSpace"\s*/>', " ", xml))
                    if history:
                        text = f"{text}\n({history.strip()})"
                    held = codes.setdefault(code, {}).get(section)
                    # More than one active version (a later operative date): the latest.
                    if not held or effective >= held[0]:
                        codes[code][section] = (effective, {"h": "", "t": text})
    count = 0
    for code, sections in sorted(codes.items()):
        with gzip.open(os.path.join(out, f"t{code}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump({k: v[1] for k, v in sections.items()}, g, ensure_ascii=False, separators=(",", ":"))
        count += len(sections)
        print(f"t{code}\t{len(sections)}", flush=True)
    return {"source": url, "titles": len(codes), "sections": count, "codes": names}


STATES = {"va": virginia, "ca": california}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in STATES:
        sys.exit(__doc__)
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    meta = STATES[sys.argv[1]](out)
    meta["exportedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(out, "release.json"), "w") as f:
        json.dump(meta, f)
