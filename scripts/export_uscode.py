"""The United States Code, section by section, for showing a cited section's
text in the app instead of linking out. From the Office of the Law Revision
Counsel's release-point XML (uscode.house.gov/download.html; USLM, public
domain as a work of the U.S. Government).

    python3 export_uscode.py current                 -> the current release point ("119-142")
    python3 export_uscode.py export <zip> <out dir>  -> <out>/t<N>.json.gz, <out>/release.json

Each title file: {"<section>": {"h": heading, "t": text, "s": status?}}. The
text is the statute itself, its subdivisions one per line with their
designations ("(a)", "(1)"), and its source credit; the editorial and
statutory notes (amendments, effective dates, references in text) are left
out. Repealed and omitted sections keep their status and heading.
"""
import gzip, io, json, os, re, sys, urllib.request, zipfile
import xml.etree.ElementTree as ET

NS = "{http://xml.house.gov/schemas/uslm/1.0}"
SITE = "https://uscode.house.gov/"
UA = {"User-Agent": "populist-uscode-export (bulk release point, weekly)"}
BLOCKS = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem",
          "subsubitem", "chapeau", "continuation", "content", "p", "sourceCredit", "quotedContent"}
SKIP = {"notes", "note", "toc", "layout"}


def current():
    with urllib.request.urlopen(urllib.request.Request(SITE + "download.html", headers=UA), timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r'download/releasepoints/us/pl/(\d+)/(\w+)/xml_uscAll@([\w-]+)\.zip', page)
    if not m:
        sys.exit("no xml_uscAll link on download.html")
    print(json.dumps({"release": m.group(3), "url": SITE + m.group(0)}))


def local(tag):
    return tag[len(NS):] if tag.startswith(NS) else tag


def text_of(section):
    """The section's text: its own number and heading left off (they're the
    key and "h"), notes skipped, one line per subdivision."""
    lines, current = [], []

    def flush():
        line = re.sub(r"\s+", " ", "".join(current)).strip()
        if line:
            lines.append(line)
        current.clear()

    def walk(el):
        if local(el.tag) in SKIP:
            return
        block = local(el.tag) in BLOCKS
        if block:
            flush()
        current.append(el.text or "")
        for child in el:
            walk(child)
            current.append(child.tail or "")
        if block:
            flush()

    for child in section:
        if local(child.tag) not in ("num", "heading"):
            walk(child)
    flush()
    # A designation alone ("(a)", "(1)") joins the line it designates.
    joined = []
    for line in lines:
        if joined and re.fullmatch(r"\([A-Za-z0-9]+\)", joined[-1]):
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return "\n".join(joined)


def export(zip_path, out):
    os.makedirs(out, exist_ok=True)
    release = None
    with zipfile.ZipFile(zip_path) as z:
        for name in sorted(n for n in z.namelist() if re.fullmatch(r"usc\d+a?\.xml", n)):
            title = re.fullmatch(r"usc0*(\d+a?)\.xml", name).group(1)
            sections = {}
            with z.open(name) as f:
                for _, el in ET.iterparse(f, events=("end",)):
                    tag = local(el.tag)
                    if tag == "docPublicationName" and el.text and "@" in el.text:
                        release = el.text.split("@", 1)[1]
                    if tag != "section":
                        continue
                    ident = el.get("identifier") or ""
                    m = re.match(rf"/us/usc/t{re.escape(title)}/s([^ /]+)", ident)
                    if not m or "..." in m.group(1):
                        el.clear()
                        continue
                    heading = el.find(NS + "heading")
                    entry = {"h": re.sub(r"\s+", " ", "".join(heading.itertext())).strip() if heading is not None else ""}
                    if el.get("status"):
                        entry["s"] = el.get("status")
                    else:
                        entry["t"] = text_of(el)
                    # The XML writes "1395w–4" with an en dash; citations use a hyphen.
                    sections[m.group(1).replace("\u2013", "-")] = entry
                    el.clear()
            with gzip.open(os.path.join(out, f"t{title}.json.gz"), "wt", encoding="utf-8") as g:
                json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))
            print(f"t{title}\t{len(sections)}")
    with open(os.path.join(out, "release.json"), "w") as f:
        json.dump({"release": release, "source": SITE + "download.html"}, f)


if __name__ == "__main__":
    if sys.argv[1:2] == ["current"]:
        current()
    elif sys.argv[1:2] == ["export"]:
        export(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
