"""American Samoa Senate measures' text, OCR'd from their PDFs (they're scans).

    python3 as_bill_texts.py <dir of bill_*.json from as_fono.py> <out-dir>

Writes <out-dir>/as/bill-text/<SB_39-8>.txt for each measure with a PDF, the
text the app's reference lookup reads a bill's citations from. A text already
there is kept (a measure's PDF doesn't change); new ones are converted until
OCR_DEADLINE seconds have passed, the rest next run.
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from as_public_laws import fetch, pdf_text   # noqa: E402


def main():
    bills_dir, out = sys.argv[1], os.path.join(sys.argv[2], "as", "bill-text")
    os.makedirs(out, exist_ok=True)
    deadline = time.time() + float(os.environ.get("OCR_DEADLINE", "18000"))
    done = new = 0
    for path in sorted(glob.glob(os.path.join(bills_dir, "bill_*.json"))):
        bill = json.load(open(path))
        links = [link["url"] for version in bill.get("versions", []) for link in version.get("links", [])]
        if not links:
            continue
        target = os.path.join(out, bill["identifier"].replace(" ", "_") + ".txt")
        if os.path.exists(target):
            done += 1
            continue
        if time.time() > deadline:
            continue
        try:
            text, how = pdf_text(fetch(links[0], binary=True))
        except Exception as error:
            print(f"warning: {bill['identifier']}: {error}", file=sys.stderr)
            continue
        if text:
            with open(target, "w") as handle:
                handle.write(text)
            new += 1
    print(f"bill texts: {done + new} ({new} new)")


if __name__ == "__main__":
    main()
