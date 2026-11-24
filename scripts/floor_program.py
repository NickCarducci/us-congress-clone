#!/usr/bin/env python3
"""What each chamber takes up next, from the Congressional Record.

The Daily Digest at the end of every Record closes with "Next Meeting of the
SENATE" and "Next Meeting of the HOUSE OF REPRESENTATIVES": when each chamber
meets next and its "Program for <day>" (the bills, nominations and votes it
plans). unitedstates/congress has no Senate counterpart to its
upcoming_house_floor task (docs.house.gov is House-only, and senate.gov's
floor_schedule.xml lists session times, not business), so this reads the
program for both chambers from the latest Record and writes it in one
chamber-neutral shape, next to the House's weekly schedule. The Record comes
from our own GovInfo mirror, like bill status and text (no API key):

    usc-run govinfo --collections=CREC --years=2026 --filter='2026-11-(19|20)'

leaves each day's package at data/govinfo/CREC/<date>/package.zip, whose
html/ holds every page of the Record, the Daily Digest's included.

Output:

    data/upcoming_floor_program/<record date>.json
    {
      "record": "CREC-2026-11-19",
      "congress": 119,
      "chambers": {
        "senate": {"meets_at": "2026-11-20T10:00:00-05:00",
                   "program": "Senate will continue consideration of ...",
                   "items": [{"bill_id": "hr1234-119", "chamber": "senate",
                              "scheduled_for": "2026-11-20", "description": "...",
                              "consideration": "program"}]},
        "house": {...}
      }
    }

Bill ids match the scraper's ("hr1234-119"), so the server can join them to
the bill index the same way as upcoming_house_floor's.

Usage: floor_program.py DATA_DIR [--record CREC-YYYY-MM-DD] [--days 10]
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import zipfile

EASTERN_OFFSETS = {"EST": "-05:00", "EDT": "-04:00"}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

# "H.R. 1234", "S. 56", "H. Res. 12", "S.J. Res. 3", "H. Con. Res. 4"
BILL_PATTERN = re.compile(
    r"\b(H\.\s?R\.|S\.|H\.\s?Res\.|S\.\s?Res\.|H\.\s?J\.\s?Res\.|S\.\s?J\.\s?Res\.|"
    r"H\.\s?Con\.\s?Res\.|S\.\s?Con\.\s?Res\.)\s?(\d{1,5})\b")
BILL_TYPES = {"hr": "hr", "s": "s", "hres": "hres", "sres": "sres", "hjres": "hjres",
              "sjres": "sjres", "hconres": "hconres", "sconres": "sconres"}


def mirrored_records(data_dir, days, today=None):
    """Record packages in the GovInfo mirror from the last `days` days, newest first."""
    today = today or datetime.date.today()
    root = os.path.join(data_dir, "govinfo", "CREC")
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return []
    records = []
    for name in names:
        day = name[len("CREC-"):] if name.startswith("CREC-") else name
        try:
            date = datetime.date.fromisoformat(day)
        except ValueError:
            continue
        package = os.path.join(root, name, "package.zip")
        if (today - date).days <= days and os.path.exists(package):
            records.append((date, package))
    return [(f"CREC-{date.isoformat()}", package) for date, package in sorted(records, reverse=True)]


def next_meeting_page(package):
    """The Daily Digest page holding "Next Meeting of the SENATE", from a package zip."""
    with zipfile.ZipFile(package) as archive:
        digest = sorted(name for name in archive.namelist() if re.search(r"/html/[^/]*-PgD[^/]*\.htm$", name))
        for name in reversed(digest):  # it closes the Digest
            page = archive.read(name).decode("utf-8", errors="replace")
            if "Next Meeting of the" in page:
                return page
    return None


def plain_text(page):
    text = re.sub(r"<[^>]+>", "", page)
    return html.unescape(text).replace("\r", "")


def bill_ids(text, congress):
    ids = []
    for match in BILL_PATTERN.finditer(text):
        kind = re.sub(r"[^a-z]", "", match.group(1).lower())
        if kind in BILL_TYPES:
            bill = f"{BILL_TYPES[kind]}{int(match.group(2))}-{congress}"
            if bill not in ids:
                ids.append(bill)
    return ids


def meeting_time(heading, record_date):
    """"10 a.m., Friday, November 20" -> an Eastern ISO timestamp."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.m\.|p\.m\.|noon)?,?\s*\w+day,\s*(\w+)\s+(\d{1,2})", heading, re.I)
    if not m:
        return None, None
    suffix = (m.group(3) or "").lower()
    hour = 12 if suffix == "noon" else int(m.group(1)) % 12 + (12 if suffix.startswith("p") else 0)
    minute = int(m.group(2) or 0)
    month = MONTHS.get(m.group(4).lower())
    if not month:
        return None, None
    year = record_date.year + (1 if month < record_date.month else 0)  # a Record in late December
    day = datetime.date(year, month, int(m.group(5)))
    # Eastern time: daylight saving from the second Sunday of March to the first of November.
    march = datetime.date(year, 3, 8 + (6 - datetime.date(year, 3, 8).weekday()) % 7)
    november = datetime.date(year, 11, 1 + (6 - datetime.date(year, 11, 1).weekday()) % 7)
    offset = EASTERN_OFFSETS["EDT" if march <= day < november else "EST"]
    return day.isoformat(), f"{day.isoformat()}T{hour:02d}:{minute:02d}:00{offset}"


def parse_next_meetings(text, record, congress):
    """The "Next Meeting" section: each chamber's meeting time, program and bills."""
    record_date = datetime.date.fromisoformat(record[len("CREC-"):])
    chambers = {}
    sections = re.split(r"Next Meeting of the (SENATE|HOUSE OF REPRESENTATIVES)", text)
    for name, body in zip(sections[1::2], sections[2::2]):
        chamber = "senate" if name == "SENATE" else "house"
        lines = [line.strip() for line in body.split("\n")]
        heading = next((line for line in lines if line), "")
        day, meets_at = meeting_time(heading, record_date)
        joined = " ".join(line for line in lines if line)
        program = re.search(r"Program for [^:]+:\s*(.*)", joined)
        program_text = program.group(1) if program else ""
        # The section ends at the next divider or the Extensions of Remarks index.
        program_text = re.split(r"_{5,}|Extensions of Remarks", program_text)[0].strip()
        items = [{"bill_id": bill, "chamber": chamber, "scheduled_for": day,
                  "meets_at": meets_at, "consideration": "program",
                  "description": sentence_with(program_text, bill)}
                 for bill in bill_ids(program_text, congress)]
        chambers[chamber] = {"meets_at": meets_at, "scheduled_for": day,
                             "program": program_text, "items": items}
    return chambers


def sentence_with(text, bill_id):
    """The program's sentence naming the bill (for the card's floor note)."""
    number = re.match(r"[a-z]+(\d+)-", bill_id).group(1)
    for sentence in re.split(r"(?<=\.)\s+(?=[A-Z])", text):
        if re.search(rf"\b{number}\b", sentence):
            return sentence.strip()
    return text[:300]


def congress_for(date):
    return (date.year - 1789) // 2 + 1 - int(date.year % 2 == 1 and date < datetime.date(date.year, 1, 3))


def run(data_dir, record=None, days=10, today=None):
    records = mirrored_records(data_dir, days, today)
    if record:
        records = [entry for entry in records if entry[0] == record]
    for candidate, package in records:
        page = next_meeting_page(package)
        if not page:
            continue
        record_date = datetime.date.fromisoformat(candidate[len("CREC-"):])
        congress = congress_for(record_date)
        chambers = parse_next_meetings(plain_text(page), candidate, congress)
        if not chambers:
            continue
        out_dir = os.path.join(data_dir, "upcoming_floor_program")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{record_date.isoformat()}.json")
        with open(path + ".tmp", "w") as out:
            json.dump({"record": candidate, "congress": congress, "chambers": chambers}, out, indent=2, sort_keys=True)
        os.replace(path + ".tmp", path)
        counts = {c: len(v["items"]) for c, v in chambers.items()}
        print(f"{candidate}: {counts} bills in the next programs -> {path}")
        return path
    print("No mirrored Record with a Next Meeting section in range", file=sys.stderr)
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data_dir")
    parser.add_argument("--record", help="A Record package id, e.g. CREC-2026-11-19")
    parser.add_argument("--days", type=int, default=10, help="How far back to look for the latest mirrored Record")
    args = parser.parse_args()
    run(args.data_dir, args.record, args.days)
