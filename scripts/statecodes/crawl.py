"""The one crawler every state's code goes through.

A state is a list of units (a title, a chapter, or one whole-code download),
each a URL, and a parser that turns a unit into section files. The crawler
keeps units.json beside the files: per unit, its Last-Modified/ETag, when it
was checked, and how many sections it gave. So a run

  * asks "changed since?" (If-Modified-Since / If-None-Match) and skips what
    hasn't changed,
  * visits never-fetched units first, then the longest-unchecked,
  * stops at its time budget, or after a few failures in a row (a site that
    starts refusing us), and saves where it got to: the next run resumes there,
  * re-checks a unit that didn't exist ("2A") only once a month.

units.json is synced to the server and pulled back before each run.
"""
import gzip, html, json, os, re, shutil, sys, tempfile, time, urllib.error, urllib.request

UA = "populist-state-code-export (weekly; resumable; one unit at a time)"
MONTH = 30 * 86400


def plain(body):
    """HTML as text: one line per paragraph."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>", "\n", body or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def get(url, attempts=3, timeout=120):
    """A plain GET, for listings."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))


class Source:
    """A fetched unit, on disk (a whole-code zip can be over a gigabyte)."""
    def __init__(self, path, key):
        self.path, self.key = path, key

    def read(self):
        with open(self.path, "rb") as f:
            return f.read()

    def text(self, encoding="utf-8"):
        raw = self.read()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or raw[1:2] == b"\x00":
            return raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-16-le", "replace")
        return raw.decode(encoding, "replace")


def fetch(url, held, path, timeout):
    """(status, headers) with the body written to path; 304 when unchanged."""
    headers = {"User-Agent": UA}
    if held.get("lastModified"):
        headers["If-Modified-Since"] = held["lastModified"]
    if held.get("etag"):
        headers["If-None-Match"] = held["etag"]
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r, open(path, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
                return 200, r.headers
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, e.headers
            if e.code in (404, 410):
                return 404, e.headers
            if attempt or e.code < 500:
                raise
        except Exception:
            if attempt:
                raise
        time.sleep(15)


class Crawl:
    def __init__(self, out, spacing=2, budget_minutes=None, timeout=300):
        self.out, self.spacing, self.timeout = out, spacing, timeout
        os.makedirs(out, exist_ok=True)
        budget = budget_minutes or float(os.environ.get("CRAWL_BUDGET_MIN", "50"))
        self.deadline = time.time() + budget * 60
        self.path = os.path.join(out, "units.json")
        try:
            with open(self.path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.units = saved.get("units", {})
        self.extra = saved.get("extra", {})   # kept for release.json ("codes" names)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"units": self.units, "extra": self.extra}, f, separators=(",", ":"))
        os.replace(tmp, self.path)

    def write(self, file_key, sections):
        with gzip.open(os.path.join(self.out, f"t{file_key}.json.gz"), "wt", encoding="utf-8") as g:
            json.dump(sections, g, ensure_ascii=False, separators=(",", ":"))

    def run(self, units, parse):
        """units: [(key, url)]; parse(Source) -> {file_key: {section: {"h", "t"}}}."""
        now = time.time()
        order = sorted(units, key=lambda u: self.units.get(u[0], {}).get("checked", 0))
        visited, failures, stopped = 0, 0, None
        with tempfile.TemporaryDirectory() as tmp:
            for key, url in order:
                held = self.units.get(key, {})
                if held.get("missing") and now - held.get("checked", 0) < MONTH:
                    visited += 1
                    continue
                if time.time() > self.deadline:
                    stopped = "time budget"
                    break
                path = os.path.join(tmp, "unit")
                try:
                    status, headers = fetch(url, held if held.get("sections") else {}, path, self.timeout)
                except Exception as e:
                    failures += 1
                    print(f"{key}\tfailed: {type(e).__name__}: {e}", flush=True)
                    if failures >= 3:
                        stopped = "refused three times in a row"
                        break
                    time.sleep(self.spacing * 5)
                    continue
                failures = 0
                visited += 1
                stamp = {"checked": time.time()}
                if status == 304:
                    held.update(stamp)
                elif status == 404:
                    held = {"missing": True, **stamp}
                else:
                    files = parse(Source(path, key)) or {}
                    for file_key, sections in files.items():
                        self.write(file_key, sections)
                    held = {"lastModified": headers.get("Last-Modified"), "etag": headers.get("ETag"),
                            "files": sorted(files), "sections": sum(len(s) for s in files.values()), **stamp}
                    print(f"{key}\t{held['sections']}", flush=True)
                self.units[key] = held
                self.save()
                time.sleep(self.spacing)
        listed = {k for k, _ in units}
        sections = sum(u.get("sections", 0) for k, u in self.units.items() if k in listed)
        files = sorted({f for k, u in self.units.items() if k in listed for f in u.get("files", [])})
        return {"titles": len(files), "sections": sections, "complete": stopped is None and visited == len(units),
                "stopped": stopped, "visited": visited, "units": len(units), **self.extra}
