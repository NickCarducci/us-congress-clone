"""Patch unitedstates/congress before install, for records it can't parse.

GovInfo BILLSTATUS records it fails on (seen in the 108th-112th and 119th
Congress archive runs, about 2,300 bills, including enacted laws):
- actions without a sourceSystem element (KeyError: 'sourceSystem');
- sponsors whose party code is longer than one letter, such as "ID"
  (Independent Democrat), which its sponsor regex rejects (ValueError).

Each fix is an exact text replacement. If upstream has changed the code, the
replacement is skipped with a warning rather than failing the run.

Usage: python3 scripts/patch_scraper.py <scraper checkout>
"""
import sys
from pathlib import Path

PATCHES = [
    ("congress/tasks/bill_info.py",
     "if item['sourceSystem'].get('code') == \"9\":",
     "if (item.get('sourceSystem') or {}).get('code') == \"9\":"),
    ("congress/tasks/bill_info.py",
     "+\\[(?P<party>[DRIL])-(?P<state>",
     "+\\[(?P<party>[A-Z]{1,3})-(?P<state>"),
]


def patch(root):
    applied = 0
    for relative, old, new in PATCHES:
        path = Path(root) / relative
        text = path.read_text()
        if new in text:
            applied += 1
            continue
        if text.count(old) != 1:
            print(f"::warning::scraper patch not applied to {relative}: expected text not found once")
            continue
        path.write_text(text.replace(old, new))
        applied += 1
    print(f"scraper patches applied: {applied}/{len(PATCHES)}")
    return applied


if __name__ == "__main__":
    patch(sys.argv[1])
