#!/usr/bin/env python3
"""Upcoming state committee hearings and the bills on their agendas, from the
Open States API (v3.openstates.org/events): their documented API over the
database their scrapers fill, for every state at once.

Writes one file per state that has any, for the server's state feed:

    OUT_DIR/<ST>.json
    {"state": "NJ", "fetched_at": "...", "events": [
      {"id": "ocd-event/...", "name": "Meeting of the Senate Community and
       Urban Affairs Committee", "start": "2026-11-30T15:00:00+00:00",
       "status": "tentative", "location": "Committee Room 6, ...",
       "bills": [{"session": "222", "identifier": "SCR 96",
                  "id": "NJ:222:SCR96"}]}]}

"id" is the bill's id in our state catalog (state, session, identifier
without spaces), so the server joins without another lookup. Only events
from now on, with bills (require_bills), not canceled.

The free tier allows few requests, so this paces itself (--pause seconds
between requests) and asks once per state, plus a page for a busy one.

Usage: state_events.py OUT_DIR [--states nj,ny] [--pause 7]
Needs OPEN_STATES_KEY.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://v3.openstates.org"
# Open States' jurisdictions (American Samoa has none there).
STATES = ("ak al ar az ca co ct dc de fl ga gu hi ia id il in ks ky la ma md me mi mn mo mp ms mt nc nd ne nh "
          "nj nm nv ny oh ok or pa pr ri sc sd tn tx ut va vi vt wa wi wv wy").split()


def get(path, pause, **params):
    url = f"{API}{path}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(url, headers={"X-API-KEY": os.environ.get("OPEN_STATES_KEY", ""),
                                                   "User-Agent": "populist-state-events/1.0"})
    for attempt in range(3):
        time.sleep(pause)
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 2:
                time.sleep(60)
                continue
            raise


def catalog_id(state, session, identifier):
    return f"{state.upper()}:{session}:{identifier.replace(' ', '')}"


def events_for(state, after, pause):
    events, page = [], 1
    while True:
        result = get("/events", pause, jurisdiction=state, after=after, require_bills="true",
                     include="agenda", per_page=20, page=page)
        for event in result.get("results", []):
            if event.get("deleted") or (event.get("status") or "").lower() in ("cancelled", "canceled"):
                continue
            bills = []
            for item in event.get("agenda") or []:
                for entity in item.get("related_entities") or []:
                    bill = entity.get("bill") if entity.get("entity_type") == "bill" else None
                    if isinstance(bill, dict) and bill.get("identifier") and bill.get("session"):
                        record = {"session": bill["session"], "identifier": bill["identifier"],
                                  "id": catalog_id(state, bill["session"], bill["identifier"])}
                        if record not in bills:
                            bills.append(record)
            # Open States sometimes lists one hearing twice under two ids.
            if bills and not any(e["name"] == event.get("name") and e["start"] == event.get("start_date") for e in events):
                events.append({"id": event.get("id"), "name": event.get("name"), "start": event.get("start_date"),
                               "status": event.get("status"), "classification": event.get("classification"),
                               "location": (event.get("location") or {}).get("name"), "bills": bills})
        pages = (result.get("pagination") or {}).get("max_page") or 1
        if page >= pages or page >= 5:
            return events
        page += 1


def run(out_dir, states=STATES, pause=7.0, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    after = (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(out_dir, exist_ok=True)
    failures = 0
    for state in states:
        try:
            events = events_for(state, after, pause)
        except Exception as error:  # one state's failure doesn't stop the rest
            failures += 1
            print(f"::warning::{state}: {error}", file=sys.stderr)
            continue
        path = os.path.join(out_dir, f"{state.upper()}.json")
        with open(path + ".tmp", "w") as out:
            json.dump({"state": state.upper(), "fetched_at": now.isoformat(), "events": events}, out, indent=2)
        os.replace(path + ".tmp", path)
        print(f"{state.upper()}: {len(events)} upcoming hearings, {sum(len(e['bills']) for e in events)} bills")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--states", help="Comma-separated, e.g. nj,ny (default: all)")
    parser.add_argument("--pause", type=float, default=7.0, help="Seconds between requests")
    args = parser.parse_args()
    chosen = args.states.lower().split(",") if args.states else STATES
    failures = run(args.out_dir, chosen, args.pause)
    sys.exit(1 if failures == len(chosen) else 0)
