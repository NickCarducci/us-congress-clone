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

New York: the Senate's Open Legislation Laws API (legislation.nysenate.gov,
free key in NEW_YORK_API_KEY), each law's full tree (full=true), one law
every few seconds, once a week. Files are t<LAWID>.json.gz ("PEN"), keyed
by section in lowercase ("2-a").
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


def new_york(out):
    key = os.environ.get("NEW_YORK_API_KEY")
    if not key:
        sys.exit("NEW_YORK_API_KEY is not set")
    base = "https://legislation.nysenate.gov/api/3/laws"
    listing = json.loads(get(f"{base}?limit=1000&key={key}"))["result"]["items"]
    names, count = {}, 0
    for law in listing:
        law_id = law["lawId"]
        tree = json.loads(get(f"{base}/{law_id}?full=true&key={key}"))["result"]["documents"]
        sections = {}
        stack = [tree]
        while stack:
            node = stack.pop()
            if node.get("docType") == "SECTION" and str(node.get("repealed")).lower() != "true":
                text = (node.get("text") or "").replace("\\n", "\n")
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                sections[str(node["locationId"]).lower()] = {"h": node.get("title") or "", "t": "\n".join(lines)}
            stack.extend((node.get("documents") or {}).get("items") or [])
        if sections:
            with gzip.open(os.path.join(out, f"t{law_id}.json.gz"), "wt", encoding="utf-8") as g:
                json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
            # As bills name it: "Vehicle & Traffic" -> "vehicle and traffic law".
            names[law_id] = law["name"].replace("&", "and")
            count += len(sections)
        print(f"t{law_id}\t{len(sections)}", flush=True)
        time.sleep(3)
    return {"source": "https://legislation.nysenate.gov/api/3/laws", "titles": len(names), "sections": count, "codes": names}


def new_jersey(out):
    import zipfile
    url = "https://pub.njleg.gov/statutes/STATUTES-TEXT.zip"
    data = get(url)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("STATUTES.TXT").decode("cp1252", "replace")
    head = re.compile(r"^(\d+[A-Z]?:\d+[A-Z]?-\d+(?:\.\d+)*[a-z]?)\.?\s+(.*\S)\s*$")
    titles, current, body = {}, None, []

    def close():
        if current:
            section, heading = current
            lines = [line.strip() for line in body if line.strip()]
            # The text often repeats the section number first ("1:1-2.  Unless…").
            if lines:
                lines[0] = re.sub(rf"^{re.escape(section)}\.?\s*", "", lines[0])
            # …or the heading again ("Murder.").
            if lines and lines[0].rstrip(".").strip() == heading.rstrip(".").strip():
                lines = lines[1:]
            titles.setdefault(section.split(":")[0], {})[section] = {"h": heading.rstrip("."), "t": "\n".join(l for l in lines if l)}

    for line in text.splitlines():
        m = head.match(line) if line[:1].isdigit() else None
        if m:
            close()
            current, body = (m.group(1), m.group(2)), []
        elif current:
            body.append(line)
    close()
    count = 0
    for title, sections in sorted(titles.items()):
        with gzip.open(os.path.join(out, f"t{title}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
        count += len(sections)
    print(f"{len(titles)} titles", flush=True)
    return {"source": url, "titles": len(titles), "sections": count}


def district_of_columbia(out):
    """The D.C. Council's own XML of the D.C. Code (github.com/DCCouncil/law-xml,
    public domain; the Council asks bulk users to take the repository instead
    of scraping code.dccouncil.gov). One zip a week. Annotations (history,
    notes) left out: statute only."""
    import xml.etree.ElementTree as ET, zipfile
    url = "https://github.com/DCCouncil/law-xml/archive/refs/heads/main.zip"
    ns = "{https://code.dccouncil.us/schemas/dc-library}"
    z = zipfile.ZipFile(io.BytesIO(get(url)))
    titles = {}

    def lines(node, depth=0):
        out_lines, label = [], ""
        for child in node:
            tag = child.tag.replace(ns, "")
            if tag == "num" and depth:
                label = (child.text or "").strip()
            elif tag in ("text", "aftertext"):
                body = " ".join("".join(child.itertext()).split())
                if body:
                    out_lines.append(f"{label} {body}".strip() if label else body)
                    label = ""
            elif tag == "para":
                out_lines.extend(lines(child, depth + 1))
            elif tag == "table":
                out_lines.extend(" | ".join(" ".join("".join(c.itertext()).split()) for c in row) for row in child.iter(f"{ns}tr"))
        if label:
            out_lines.insert(0, label)
        return out_lines

    for name in z.namelist():
        m = re.search(r"/us/dc/council/code/titles/([^/]+)/sections/([^/]+)\.xml$", name)
        if not m:
            continue
        root = ET.fromstring(z.read(name))
        section = (root.findtext(f"{ns}num") or m.group(2)).strip()
        text = lines(root)
        if not text and root.find(f"{ns}reason") is not None:
            continue   # repealed / expired placeholders
        titles.setdefault(m.group(1), {})[section] = {"h": (root.findtext(f"{ns}heading") or "").strip().rstrip("."), "t": "\n".join(text)}
    count = 0
    for title, sections in sorted(titles.items()):
        with gzip.open(os.path.join(out, f"t{title}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
        count += len(sections)
    print(f"{len(titles)} titles", flush=True)
    return {"source": "https://github.com/DCCouncil/law-xml", "titles": len(titles), "sections": count}


def south_dakota(out):
    """The Legislative Research Council's statutes API (sdlegislature.gov/api),
    no key, robots.txt allows it: one request per title returns every section
    (UTF-16 HTML, one document per section). One title every 3 seconds, weekly."""
    base = "https://sdlegislature.gov/api/Statutes"
    count, done = 0, 0
    for n in range(1, 70):
        for title in (str(n), f"{n}A", f"{n}B"):
            try:
                raw = get(f"{base}/{title}.html?all=true", attempts=1)
            except Exception:
                time.sleep(1)   # no such title ("2A")
                continue
            page = raw.decode("utf-16-le", "replace") if raw[1:2] == b"\x00" else raw.decode("utf-8", "replace")
            sections = {}
            for doc in page.split("<hr>"):
                m = re.search(r'class="[^"]*SENU">([0-9A-Z]+-[0-9A-Z.]+-[0-9A-Z.]+)</span>.*?class="[^"]*CL">(.*?)</span></p>(.*?)</div>', doc, re.S)
                if not m:
                    continue
                body = [p for p in plain(m.group(3)).splitlines() if p.strip()]
                sections[m.group(1)] = {"h": html.unescape(m.group(2)).strip().rstrip("."), "t": "\n".join(body)}
            time.sleep(3)
            if not sections:
                continue
            with gzip.open(os.path.join(out, f"t{title}.json.gz"), "wt", encoding="utf-8") as g:
                json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
            count += len(sections)
            done += 1
            print(f"t{title}\t{len(sections)}", flush=True)
    if not done:
        sys.exit("no South Dakota titles (format changed?)")
    return {"source": f"{base}/<title>.html?all=true", "titles": done, "sections": count}


def utah(out):
    """The Office of Legislative Research and General Counsel's code service
    (glen.le.utah.gov, developer token in UTAH_API_KEY), the official electronic
    Utah Code. Its terms: cache a copy, check at most once a day. One title
    every 3 seconds, weekly."""
    import xml.etree.ElementTree as ET
    key = os.environ.get("UTAH_API_KEY")
    if not key:
        sys.exit("UTAH_API_KEY is not set")
    base = "https://glen.le.utah.gov/code"
    listing = ET.fromstring(get(f"{base}/list/{key}"))
    numbers = [t.get("number") for t in listing.iter("title") if t.get("number")]

    def lines(node, number=""):
        # "76-1-101.5(7)(a)" -> "(a)"; inline elements stay on their line.
        out_lines = []
        current = ["(" + number.rsplit("(", 1)[-1] + " "] if "(" in number else []
        current.append(node.text or "")

        def flush():
            line = " ".join("".join(current).split())
            if line:
                out_lines.append(line)
            current.clear()

        for child in node:
            if child.tag == "subsection":
                flush()
                out_lines.extend(lines(child, child.get("number") or ""))
            elif child.tag not in ("histories", "catchline", "effdate"):
                current.append(" ".join("".join(child.itertext()).split()) or " ")
            current.append(child.tail or "")
        flush()
        return out_lines

    count = 0
    for number in numbers:
        root = ET.fromstring(get(f"{base}/{number}/{key}"))
        sections = {}
        for s in root.iter("section"):
            sections[s.get("number")] = {"h": (s.findtext("catchline") or "").strip().rstrip("."), "t": "\n".join(lines(s))}
        with gzip.open(os.path.join(out, f"t{number}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
        count += len(sections)
        print(f"t{number}\t{len(sections)}", flush=True)
        time.sleep(3)
    return {"source": "https://le.utah.gov/data/developer.htm", "titles": len(numbers), "sections": count}


def iowa(out):
    """The Legislative Services Agency's Iowa Code XML (legis.iowa.gov, one
    *_slim.xml per chapter, linked from each title's chapter list; robots.txt
    allows it). No license or rate limit published. One chapter every 2
    seconds, weekly. Files are t<chapter>.json.gz ("321J"), keyed "321J.2"."""
    import xml.etree.ElementTree as ET
    site = "https://www.legis.iowa.gov"
    first = get(f"{site}/law/iowaCode").decode("utf-8", "replace")
    years = sorted(set(int(y) for y in re.findall(r"year=(\d{4})", first))) or [int(time.strftime("%Y"))]
    year = years[-1]
    titles = sorted(set(re.findall(r"chapters\?title=([IVXL]+)", first))) or \
        "I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI".split()
    chapters = []
    for t in titles:
        page = get(f"{site}/law/iowaCode/chapters?title={t}&year={year}").decode("utf-8", "replace")
        for ch in re.findall(r"attachments/([0-9A-Z]+)_slim\.xml", page):
            if ch not in chapters:
                chapters.append(ch)
        time.sleep(2)
    X, S = "{http://www.w3.org/1999/xhtml}", "{urn:legix:slim}"
    LABEL = {"subsection": "{}.", "letteredPara": "{}.", "subpara": "({})", "subparaDiv": "({})"}

    def words(node):
        return " ".join("".join(node.itertext()).split())

    def lines(node, label=""):
        out_lines = []
        for child in node:
            cls = child.get("class") or ""
            if cls in ("history", "footnotes", "heading"):
                continue
            if child.tag == f"{X}p":
                body = words(child)
                if body:
                    out_lines.append(f"{label} {body}".strip())
                    label = ""
            elif child.tag == f"{X}div":
                ident = child.find(f"{X}div[@class='heading']/{X}span[@class='identifier']")
                sub = LABEL.get(cls, "{}").format(words(ident)) if ident is not None else ""
                out_lines.extend(lines(child, sub))
        if label:
            out_lines.insert(0, label)
        return out_lines

    count, done = 0, 0
    for ch in chapters:
        try:
            root = ET.fromstring(get(f"{site}/docs/publications/ICC/{year}/attachments/{ch}_slim.xml", attempts=2))
        except Exception:
            time.sleep(2)
            continue
        sections = {}
        for s in root.iter(f"{S}Section"):
            number = (s.get("id") or "").removeprefix("sec")
            note = s.find(f"{X}div[@class='heading']/{X}span[@class='headnote']")
            text = lines(s)
            if number and text:
                sections[number] = {"h": (words(note) if note is not None else "").rstrip("."), "t": "\n".join(text)}
        if sections:
            with gzip.open(os.path.join(out, f"t{ch}.json.gz"), "wt", encoding="utf-8") as g:
                json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
            count += len(sections)
            done += 1
        time.sleep(2)
    print(f"{done} chapters", flush=True)
    if not done:
        sys.exit("no Iowa chapters (format changed?)")
    return {"source": f"{site}/law/iowaCode", "year": year, "titles": done, "sections": count}


STATES = {"va": virginia, "ca": california, "ny": new_york, "nj": new_jersey,
          "dc": district_of_columbia, "sd": south_dakota, "ut": utah, "ia": iowa}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in STATES:
        sys.exit(__doc__)
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    meta = STATES[sys.argv[1]](out)
    meta["exportedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(out, "release.json"), "w") as f:
        json.dump(meta, f)
