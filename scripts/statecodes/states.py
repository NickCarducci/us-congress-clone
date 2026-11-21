"""Each jurisdiction's code: where its units are listed, and how a unit parses.

A state is STATES[st] = State(units, parse, spacing, timeout, source). Its
terms of use are noted with it; read a state's terms before adding one, and
take only statutory text (publishers' annotations are copyrightable).
Section files: t<file key>.json.gz, {"<section>": {"h": heading, "t": text}}.
"""
import csv, io, json, os, re, sys, urllib.parse, xml.etree.ElementTree as ET, zipfile
from dataclasses import dataclass
from typing import Callable
from .crawl import get, plain
from .pages import links, split_sections

csv.field_size_limit(sys.maxsize)


@dataclass
class State:
    source: str
    units: Callable          # (crawl) -> [(key, url)]
    parse: Callable          # (crawl, Source) -> {file_key: sections}
    spacing: float = 3
    timeout: int = 300


def words(node):
    return " ".join("".join(node.itertext()).split())


# Virginia: the Law Portal's per-title CSVs (law.lis.virginia.gov/law-library),
# titles from its JSON web service. The portal already leaves out what Michie
# (Matthew Bender) holds copyright in: annotations, revisors' notes.
VA = "https://law.lis.virginia.gov"

def va_units(crawl):
    titles = json.loads(get(f"{VA}/api/CoVTitlesGetListOfJson/"))
    numbers = [str(t["TitleNumber"]).strip() for t in titles]
    return [(n, f"{VA}/CSV/CoVTitle_{n}.csv") for n in numbers if re.fullmatch(r"\d+(\.\d+)?", n)]

def va_parse(crawl, src):
    sections = {}
    for row in csv.DictReader(io.StringIO(src.read().decode("utf-8-sig", "replace"))):
        section = (row.get("Section") or "").strip()
        if section:
            sections[section] = {"h": (row.get("Title") or "").strip(), "t": plain(row.get("Body"))}
    return {src.key: sections}


# California: the Legislature's downloadable data (downloads.leginfo.legislature.ca.gov;
# leginfo itself sits behind a bot challenge and asks bulk users to come here).
# The codes are only in the session pubinfo_<year>.zip (rebuilt Sundays):
# LAW_SECTION_TBL + one .lob per section, CODES_TBL for the codes' names.
CA = "https://downloads.leginfo.legislature.ca.gov/"

def ca_units(crawl):
    years = sorted(int(y) for y in re.findall(r"pubinfo_(\d{4})\.zip", get(CA).decode("utf-8", "replace")))
    if not years:
        sys.exit("no pubinfo_<year>.zip in the downloads index")
    return [(f"pubinfo_{years[-1]}", f"{CA}pubinfo_{years[-1]}.zip")]

def ca_parse(crawl, src):
    unquote = lambda v: None if v in ("NULL", "") else v.strip("`")
    with zipfile.ZipFile(src.path) as z:
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
    crawl.extra["codes"] = names
    return {code: {k: v[1] for k, v in sections.items()} for code, sections in codes.items()}


# New York: the Senate's Open Legislation Laws API (free key, NEW_YORK_API_KEY),
# each law's full tree. Files keyed by section in lowercase ("2-a").
NY = "https://legislation.nysenate.gov/api/3/laws"

def ny_key():
    key = os.environ.get("NEW_YORK_API_KEY")
    if not key:
        sys.exit("NEW_YORK_API_KEY is not set")
    return key

def ny_units(crawl):
    listing = json.loads(get(f"{NY}?limit=1000&key={ny_key()}"))["result"]["items"]
    # As bills name it: "Vehicle & Traffic" -> "vehicle and traffic law".
    crawl.extra["codes"] = {law["lawId"]: law["name"].replace("&", "and") for law in listing}
    return [(law["lawId"], f"{NY}/{law['lawId']}?full=true&key={ny_key()}") for law in listing]

def ny_parse(crawl, src):
    sections, stack = {}, [json.loads(src.read())["result"]["documents"]]
    while stack:
        node = stack.pop()
        if node.get("docType") == "SECTION" and str(node.get("repealed")).lower() != "true":
            lines = [l.strip() for l in (node.get("text") or "").replace("\\n", "\n").splitlines() if l.strip()]
            sections[str(node["locationId"]).lower()] = {"h": node.get("title") or "", "t": "\n".join(lines)}
        stack.extend((node.get("documents") or {}).get("items") or [])
    return {src.key: sections} if sections else {}


# New Jersey: the Legislature's whole statute book, plain text, rebuilt weekdays.
NJ = "https://pub.njleg.gov/statutes/STATUTES-TEXT.zip"

def nj_parse(crawl, src):
    with zipfile.ZipFile(src.path) as z:
        text = z.read("STATUTES.TXT").decode("cp1252", "replace")
    head = re.compile(r"^(\d+[A-Z]?:\d+[A-Z]?-\d+(?:\.\d+)*[a-z]?)\.?\s+(.*\S)\s*$")
    titles, current, body = {}, None, []

    def close():
        if current:
            section, heading = current
            lines = [l.strip() for l in body if l.strip()]
            if lines:   # the text often repeats the number first ("1:1-2.  Unless…")
                lines[0] = re.sub(rf"^{re.escape(section)}\.?\s*", "", lines[0])
            if lines and lines[0].rstrip(".").strip() == heading.rstrip(".").strip():
                lines = lines[1:]   # …or the heading again ("Murder.")
            titles.setdefault(section.split(":")[0], {})[section] = {"h": heading.rstrip("."), "t": "\n".join(l for l in lines if l)}

    for line in text.splitlines():
        m = head.match(line) if line[:1].isdigit() else None
        if m:
            close()
            current, body = (m.group(1), m.group(2)), []
        elif current:
            body.append(line)
    close()
    return titles


# District of Columbia: the Council's own XML (github.com/DCCouncil/law-xml, public
# domain; code.dccouncil.gov asks bulk users to take the repository, not scrape).
# Annotations (history, notes) left out.
DC = "https://github.com/DCCouncil/law-xml/archive/refs/heads/main.zip"
DCNS = "{https://code.dccouncil.us/schemas/dc-library}"

def dc_lines(node, depth=0):
    out, label = [], ""
    for child in node:
        tag = child.tag.replace(DCNS, "")
        if tag == "num" and depth:
            label = (child.text or "").strip()
        elif tag in ("text", "aftertext"):
            body = " ".join("".join(child.itertext()).split())
            if body:
                out.append(f"{label} {body}".strip() if label else body)
                label = ""
        elif tag == "para":
            out.extend(dc_lines(child, depth + 1))
        elif tag == "table":
            out.extend(" | ".join(words(c) for c in row) for row in child.iter(f"{DCNS}tr"))
    if label:
        out.insert(0, label)
    return out

def dc_parse(crawl, src):
    titles = {}
    with zipfile.ZipFile(src.path) as z:
        for name in z.namelist():
            m = re.search(r"/us/dc/council/code/titles/([^/]+)/sections/([^/]+)\.xml$", name)
            if not m:
                continue
            root = ET.fromstring(z.read(name))
            text = dc_lines(root)
            if not text and root.find(f"{DCNS}reason") is not None:
                continue   # repealed / expired placeholders
            section = (root.findtext(f"{DCNS}num") or m.group(2)).strip()
            titles.setdefault(m.group(1), {})[section] = {"h": (root.findtext(f"{DCNS}heading") or "").strip().rstrip("."), "t": "\n".join(text)}
    return titles


# South Dakota: the LRC's statutes API, a whole title per request (UTF-16 HTML,
# one document per section). No key; robots.txt allows it. There's no titles
# list, so every number is a candidate; the crawler re-checks absent ones monthly.
SD = "https://sdlegislature.gov/api/Statutes"

def sd_units(crawl):
    return [(t, f"{SD}/{t}.html?all=true") for n in range(1, 70) for t in (str(n), f"{n}A", f"{n}B")]

def sd_parse(crawl, src):
    sections = {}
    for doc in src.text().split("<hr>"):
        m = re.search(r'class="[^"]*SENU">([0-9A-Z]+-[0-9A-Z.]+-[0-9A-Z.]+)</span>.*?class="[^"]*CL">(.*?)</span></p>(.*?)</div>', doc, re.S)
        if m:
            sections[m.group(1)] = {"h": plain(m.group(2)).rstrip("."), "t": plain(m.group(3))}
    return {src.key: sections} if sections else {}


# Utah: the official Utah Code service (glen.le.utah.gov, developer token in
# UTAH_API_KEY). Its terms: cache a copy, check at most once a day. Never use
# le.utah.gov's own xcode files in its place.
UT = "https://glen.le.utah.gov/code"

def ut_key():
    key = os.environ.get("UTAH_API_KEY")
    if not key:
        sys.exit("UTAH_API_KEY is not set")
    return key

def ut_units(crawl):
    listing = ET.fromstring(get(f"{UT}/list/{ut_key()}"))
    return [(t.get("number"), f"{UT}/{t.get('number')}/{ut_key()}") for t in listing.iter("title") if t.get("number")]

def ut_lines(node, number=""):
    # "76-1-101.5(7)(a)" -> "(a)"; inline elements stay on their line.
    out = []
    current = ["(" + number.rsplit("(", 1)[-1] + " "] if "(" in number else []
    current.append(node.text or "")

    def flush():
        line = " ".join("".join(current).split())
        if line:
            out.append(line)
        current.clear()

    for child in node:
        if child.tag == "subsection":
            flush()
            out.extend(ut_lines(child, child.get("number") or ""))
        elif child.tag not in ("histories", "catchline", "effdate"):
            current.append(words(child) or " ")
        current.append(child.tail or "")
    flush()
    return out

def ut_parse(crawl, src):
    root = ET.fromstring(src.read())
    sections = {s.get("number"): {"h": (s.findtext("catchline") or "").strip().rstrip("."), "t": "\n".join(ut_lines(s))}
                for s in root.iter("section")}
    return {src.key: sections} if sections else {}


# Iowa: the Legislative Services Agency's Code XML, one *_slim.xml per chapter,
# listed per title. robots.txt allows it; no terms published.
IA = "https://www.legis.iowa.gov"
X, SLIM = "{http://www.w3.org/1999/xhtml}", "{urn:legix:slim}"
IA_LABEL = {"subsection": "{}.", "letteredPara": "{}.", "subpara": "({})", "subparaDiv": "({})"}

def ia_units(crawl):
    first = get(f"{IA}/law/iowaCode").decode("utf-8", "replace")
    year = max([int(y) for y in re.findall(r"year=(\d{4})", first)] or [0]) or None
    if not year:
        sys.exit("no Code year on the Iowa Code page")
    titles = sorted(set(re.findall(r"chapters\?title=([IVXL]+)", first)))
    chapters = []
    for t in titles:
        page = get(f"{IA}/law/iowaCode/chapters?title={t}&year={year}").decode("utf-8", "replace")
        chapters += [c for c in re.findall(r"attachments/([0-9A-Z]+)_slim\.xml", page) if c not in chapters]
    return [(c, f"{IA}/docs/publications/ICC/{year}/attachments/{c}_slim.xml") for c in chapters]

def ia_lines(node, label=""):
    out = []
    for child in node:
        cls = child.get("class") or ""
        if cls in ("history", "footnotes", "heading"):
            continue
        if child.tag == f"{X}p":
            body = words(child)
            if body:
                out.append(f"{label} {body}".strip())
                label = ""
        elif child.tag == f"{X}div":
            ident = child.find(f"{X}div[@class='heading']/{X}span[@class='identifier']")
            out.extend(ia_lines(child, IA_LABEL.get(cls, "{}").format(words(ident)) if ident is not None else ""))
    if label:
        out.insert(0, label)
    return out

def ia_parse(crawl, src):
    sections = {}
    for s in ET.fromstring(src.read()).iter(f"{SLIM}Section"):
        number = (s.get("id") or "").removeprefix("sec")
        note = s.find(f"{X}div[@class='heading']/{X}span[@class='headnote']")
        text = ia_lines(s)
        if number and text:
            sections[number] = {"h": (words(note) if note is not None else "").rstrip("."), "t": "\n".join(text)}
    return {src.key: sections} if sections else {}


# Michigan: the Legislature's MCL XML, one "Chapter <n>.xml" per chapter (UTF-16).
# Its Automated Data Collection Policy allows automated collection at no more
# than one request a second, names this directory, and may block without notice
# under load.
MI = "https://legislature.mi.gov/documents/mcl/"

def mi_units(crawl):
    chapters = sorted(set(re.findall(r"Chapter ([0-9A-Za-z]+)\.xml", get(MI).decode("utf-8", "replace"))))
    return [(c, MI + urllib.parse.quote(f"Chapter {c}.xml")) for c in chapters]

def mi_parse(crawl, src):
    sections = {}
    for s in ET.fromstring(src.read()).iter("MCLSectionInfo"):
        number = (s.findtext("MCLNumber") or "").strip()
        if s.findtext("Repealed") == "true" or not number:
            continue
        text = plain(re.sub(r"(?s)<Section-Number>.*?</Section-Number>", "", s.findtext("BodyText") or ""))
        if text:
            sections[number] = {"h": (s.findtext("CatchLine") or "").strip().rstrip("."), "t": text}
    return {src.key: sections} if sections else {}


# Pennsylvania: the General Assembly's Consolidated Statutes (palegis.us), one page
# per title (the text its title viewer loads). The legal notice is a warranty
# disclaimer and copyright-agent notice only; robots.txt doesn't cover /statutes.
# Purdon's (West) annotations are not on this site.
PA = "https://www.palegis.us/statutes/consolidated"

def pa_units(crawl):
    titles = sorted({int(t) for t in links(PA, r"txtType=HTM&amp;ttl=(\d+)")})
    return [(str(t), f"{PA}/view-statute?iFrame=true&txtType=HTM&ttl={t}") for t in titles]

def pa_parse(crawl, src):
    sections = split_sections(src.text(), r"<b>\s*&#167;\s*(?P<num>\d+(?:\.\d+)*)\.\s*(?:&nbsp;|\s)*(?P<heading>.*?)</b>",
                              drop=[r'<div class="Comment">.*?</div>'])
    return {src.key: sections} if sections else {}


one = lambda key, url: (lambda crawl: [(key, url)])

STATES = {
    "va": State(f"{VA}/law-library", va_units, va_parse),
    "ca": State(CA, ca_units, ca_parse, spacing=0, timeout=3600),
    "ny": State(NY, ny_units, ny_parse),
    "nj": State(NJ, one("statutes", NJ), nj_parse, spacing=0, timeout=900),
    "dc": State("https://github.com/DCCouncil/law-xml", one("law-xml", DC), dc_parse, spacing=0, timeout=900),
    "sd": State(f"{SD}/<title>.html?all=true", sd_units, sd_parse),
    "ut": State("https://le.utah.gov/data/developer.htm", ut_units, ut_parse),
    "ia": State(f"{IA}/law/iowaCode", ia_units, ia_parse, spacing=2),
    "mi": State(MI, mi_units, mi_parse, spacing=2, timeout=900),
    "pa": State(PA, pa_units, pa_parse, spacing=3, timeout=900),
}
