"""Exports Open States' monthly PostgreSQL dump, already restored into a local
database, as one <st>_<session>.json.gz per state and session: a JSON list of
bills in the shape Open States' own session JSON uses, which the app's
import-openstates-bulk.cjs reads (identifier, title, legislative_session,
chamber, classification, subject, abstracts, sources, actions with
organization__name, sponsors with primary).

    python3 export_dump_sessions.py <out-dir> [--first-year 2009] [--states nj,pa]

Connects with the usual PG* environment variables. Prints one line per
session (state, session, bills, bytes) and a total, for the workflow summary.
"""
import argparse
import gzip
import json
import os
import re

import psycopg2
import psycopg2.extras

STATES = {"ak", "al", "ar", "az", "ca", "co", "ct", "dc", "de", "fl", "ga", "hi", "ia", "id", "il", "in",
          "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo", "ms", "mt", "nc", "nd", "ne", "nh", "nj",
          "nm", "nv", "ny", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa",
          "wi", "wv", "wy"}

# The state's part of a jurisdiction id: ocd-jurisdiction/country:us/state:nj/government,
# or district:dc for Washington.
JURISDICTION = re.compile(r"/(?:state|district):([a-z]{2})/")

SESSIONS = """
SELECT s.id, s.identifier, s.start_date, j.id AS jurisdiction_id
  FROM opencivicdata_legislativesession s
  JOIN opencivicdata_jurisdiction j ON j.id = s.jurisdiction_id
"""

BILLS = """
SELECT b.id, b.identifier, b.title, b.classification, b.subject, o.classification AS chamber
  FROM opencivicdata_bill b
  LEFT JOIN opencivicdata_organization o ON o.id = b.from_organization_id
 WHERE b.legislative_session_id = %s
"""

# Children for one session's bills, keyed by bill id.
CHILDREN = {
    "actions": """
        SELECT a.bill_id, a.date, a.description, a."order", o.name AS organization__name
          FROM opencivicdata_billaction a
          JOIN opencivicdata_bill b ON b.id = a.bill_id
          LEFT JOIN opencivicdata_organization o ON o.id = a.organization_id
         WHERE b.legislative_session_id = %s""",
    "sponsors": """
        SELECT s.bill_id, s.name, s."primary"
          FROM opencivicdata_billsponsorship s
          JOIN opencivicdata_bill b ON b.id = s.bill_id
         WHERE b.legislative_session_id = %s""",
    "abstracts": """
        SELECT x.bill_id, x.abstract
          FROM opencivicdata_billabstract x
          JOIN opencivicdata_bill b ON b.id = x.bill_id
         WHERE b.legislative_session_id = %s""",
    "sources": """
        SELECT x.bill_id, x.url
          FROM opencivicdata_billsource x
          JOIN opencivicdata_bill b ON b.id = x.bill_id
         WHERE b.legislative_session_id = %s""",
}


def array(value):
    """Columns are restored as text: '{a,b}' arrays and JSON lists alike."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("["):
        return json.loads(text)
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1]
        if not inner:
            return []
        return [item.strip('"').replace('\\"', '"') for item in re.findall(r'"(?:[^"\\]|\\.)*"|[^,]+', inner)]
    return [text]


def year(value):
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--first-year", type=int, default=0)
    parser.add_argument("--states", default="")
    args = parser.parse_args()
    only = {s.strip().lower() for s in args.states.split(",") if s.strip()}
    os.makedirs(args.out, exist_ok=True)

    connection = psycopg2.connect("")
    cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(SESSIONS)
    sessions = []
    for row in cursor.fetchall():
        match = JURISDICTION.search(row["jurisdiction_id"] or "")
        state = match.group(1) if match else None
        if state not in STATES or (only and state not in only):
            continue
        # An undated session is kept: Open States leaves some current ones undated.
        if args.first_year and year(row["start_date"]) and year(row["start_date"]) < args.first_year:
            continue
        sessions.append((state, row))

    total_bills = total_bytes = 0
    for state, session in sorted(sessions, key=lambda item: (item[0], str(item[1]["start_date"] or "9999"))):
        cursor.execute(BILLS, (session["id"],))
        bills = {row["id"]: {"identifier": row["identifier"], "title": row["title"],
                             "legislative_session": session["identifier"],
                             "chamber": row["chamber"] if row["chamber"] in ("upper", "lower", "legislature") else None,
                             "classification": array(row["classification"]), "subject": array(row["subject"]),
                             "actions": [], "sponsors": [], "abstracts": [], "sources": []}
                 for row in cursor.fetchall()}
        if not bills:
            continue
        for key, sql in CHILDREN.items():
            cursor.execute(sql, (session["id"],))
            for row in cursor.fetchall():
                bill = bills.get(row.pop("bill_id"))
                if bill is None:
                    continue
                if key == "actions":
                    row["order"] = int(row["order"]) if row["order"] not in (None, "") else 0
                if key == "sponsors":
                    row["primary"] = str(row["primary"]).lower() in ("t", "true", "1")
                if key == "abstracts":
                    row = {"abstract": row["abstract"]}
                if key == "sources":
                    row = {"url": row["url"]}
                bill[key].append(dict(row))
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", session["identifier"])
        path = os.path.join(args.out, state, f"{state}_{safe}.json.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(list(bills.values()), handle, separators=(",", ":"), default=str)
        size = os.path.getsize(path)
        total_bills += len(bills)
        total_bytes += size
        print(f"{state}\t{session['identifier']}\t{len(bills)}\t{size}", flush=True)
    print(f"TOTAL\t{len(sessions)} sessions\t{total_bills}\t{total_bytes}")


if __name__ == "__main__":
    main()
