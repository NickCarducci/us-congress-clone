"""Checks a scrape's output so far: is what was loaded proper bill data?

    python3 check_scrape.py <dir of bill_*.json> [--session 2026] [--max-invalid 0.02]

Each bill_*.json must parse and have a bill number, a title, the session being
scraped (when given) and a list of actions. Prints one JSON line
{"bills", "invalid", "examples", "proper"} and exits 0 when proper, 1 when more
than --max-invalid of the bills (and at least 3) aren't. No bills yet is proper
(a slow start, or a session with none); the caller decides what that means.
Files still being written (unparseable and modified in the last minute) are skipped.
"""
import argparse
import glob
import json
import os
import sys
import time


def problem(bill, session):
    if not isinstance(bill, dict):
        return "not an object"
    if not str(bill.get("identifier") or "").strip():
        return "no bill number"
    if not str(bill.get("title") or "").strip():
        return "no title"
    if session and str(bill.get("legislative_session")) != session:
        return f"session {bill.get('legislative_session')!r}, expected {session!r}"
    if not isinstance(bill.get("actions"), list):
        return "no action list"
    return None


def check(directory, session=None, max_invalid=0.02, now=None):
    now = now or time.time()
    bills = invalid = 0
    examples = []
    for path in sorted(glob.glob(os.path.join(directory, "bill_*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                bill = json.load(handle)
        except (OSError, ValueError):
            if now - os.path.getmtime(path) < 60:
                continue   # being written
            bill = None
        bills += 1
        reason = problem(bill, session) if bill is not None else "unreadable JSON"
        if reason:
            invalid += 1
            if len(examples) < 5:
                examples.append(f"{os.path.basename(path)}: {reason}")
    proper = not (invalid >= 3 and invalid > max_invalid * bills)
    return {"bills": bills, "invalid": invalid, "examples": examples, "proper": proper}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--session", default="")
    parser.add_argument("--max-invalid", type=float, default=0.02)
    args = parser.parse_args()
    result = check(args.directory, args.session or None, args.max_invalid)
    print(json.dumps(result))
    sys.exit(0 if result["proper"] else 1)
