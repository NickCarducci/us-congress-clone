"""Small fixes to Open States' scrapers for changes on the legislatures' own
sites, applied before the image is built (like patch_scraper.py for the
congress scraper). Each patch skips with a warning once upstream has changed
the code it targets, so a fixed upstream never breaks the build.

    python3 patch_state_scrapers.py <openstates-scrapers checkout>
"""
import pathlib
import sys

PATCHES = [
    # South Carolina now pads the chamber cell (" Senate "); the lookup expected
    # the bare name, so every bill with an action failed (KeyError: ' Senate ').
    ("scrapers/sc/bills.py",
     '''{"Senate": "upper", "House": "lower", None: "legislature"}[
                chamber_td.text
            ]''',
     '''{"Senate": "upper", "House": "lower", None: "legislature"}[
                (chamber_td.text or "").strip() or None
            ]'''),
    # South Carolina occasionally serves a bill page without its summary block
    # (S 304 crashed a 2-hour run with IndexError, then loaded fine on retry).
    # Skip that one bill with a warning; the next run picks it up.
    ("scrapers/sc/bills.py",
     '''        bill_div = doc.xpath('//div[@style="margin:0 0 40px 0;"]')[0]
''',
     '''        bill_divs = doc.xpath('//div[@style="margin:0 0 40px 0;"]')
        if not bill_divs:
            self.warning("no bill summary at %s; skipped this run" % bill_detail_url)
            return
        bill_div = bill_divs[0]
'''),
    # Connecticut's bulk CSVs now start with a UTF-8 byte-order mark, so the
    # first column read as "\ufeffcomm_code" (KeyError: 'comm_code').
    ("scrapers/ct/utils.py",
     '''        text = data.content.decode("utf-8")
    except UnicodeDecodeError:
        text = data.content.decode("cp1252", errors="replace")''',
     '''        text = data.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.content.decode("cp1252", errors="replace").removeprefix("\u00ef\u00bb\u00bf")'''),
    # Maryland's site lists a 2027 regular and a 2026 special session the
    # scraper's metadata doesn't have yet; os-update refuses to run until every
    # listed session is known. Ignore them until upstream adds them (UNLESS
    # below drops this patch once upstream knows either session).
    ("scrapers/md/__init__.py",
     '''    ignored_scraped_sessions = [
''',
     '''    ignored_scraped_sessions = [
        "2027 Regular Session",  # patched in by us-congress-clone until upstream adds it
        "2026 Special Session",  # patched in by us-congress-clone until upstream adds it
'''),
]

# A patch is skipped when its file already contains any of these: upstream has
# done properly what the patch worked around.
UNLESS = {
    "scrapers/md/__init__.py": ['"_scraped_name": "2027 Regular Session"', '"_scraped_name": "2026 Special Session"'],
}


def main(root):
    root = pathlib.Path(root)
    for relative, old, new in PATCHES:
        path = root / relative
        text = path.read_text()          # a missing file is a real error
        if new not in text and any(marker in text for marker in UNLESS.get(relative, [])):
            print(f"{relative}: upstream now handles this; patch not needed")
        elif new in text:
            print(f"{relative}: already patched")
        elif old in text:
            path.write_text(text.replace(old, new, 1))
            print(f"{relative}: patched")
        else:
            print(f"::warning::{relative}: code changed upstream; patch skipped")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
