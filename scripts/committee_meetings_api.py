#!/usr/bin/env python3
"""Upcoming House and Senate committee meetings, from the Congress.gov API.

The Library of Congress's documented API over its database
(api.congress.gov/v3/committee-meeting), not a scrape: each meeting's time
(UTC), status, committees and the bills it takes up. Replaces
unitedstates/congress's committee_meetings task, which reads docs.house.gov's
web pages and broke twice in a day when the site changed.

Writes the shape that task wrote, so the server reads it unchanged:

    DATA_DIR/committee_meetings_house.json, committee_meetings_senate.json
    [{"chamber": "house", "congress": 119, "event_id": "119601",
      "committee": "House Judiciary", "committee_names": [...],
      "occurs_at": "2026-12-01T15:00:00Z", "status": "Scheduled",
      "type": "Hearing", "topic": "...", "bill_ids": ["hr1234-119"]}]

Only meetings still to come (and not canceled or postponed). Each meeting's
details are cached by its update time (CACHE_FILE), so a run fetches only the
meetings that changed since the last one.

Usage: committee_meetings_api.py DATA_DIR [--cache FILE] [--days 60]
Needs CONGRESS_API_KEY (api.data.gov).
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.congress.gov/v3"
DROPPED_STATUSES = {"canceled", "cancelled", "postponed"}


def api_key():
    return os.environ.get("CONGRESS_API_KEY") or "DEMO_KEY"


def get(path, **params):
    params.update({"format": "json", "api_key": api_key()})
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "populist-committee-meetings/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 3:
                time.sleep(30 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def congress_for(date):
    return (date.year - 1789) // 2 + 1 - int(date.year % 2 == 1 and date < datetime.date(date.year, 1, 3))


def changed_since(congress, chamber, since):
    """(eventId, updateDate) for meetings updated since `since`, newest first."""
    offset, found = 0, []
    while True:
        page = get(f"/committee-meeting/{congress}/{chamber}", limit=250, offset=offset,
                   fromDateTime=since.strftime("%Y-%m-%dT%H:%M:%SZ"))
        meetings = page.get("committeeMeetings", [])
        found += [(m["eventId"], m.get("updateDate")) for m in meetings]
        if len(meetings) < 250:
            return found
        offset += 250


def bill_ids(meeting):
    related = (meeting.get("relatedItems") or {}).get("bills") or []
    ids = []
    for bill in related:
        if bill.get("type") and bill.get("number") and bill.get("congress"):
            key = f"{bill['type'].lower()}{bill['number']}-{bill['congress']}"
            if key not in ids:
                ids.append(key)
    return ids


def record(meeting, chamber, congress, event_id):
    names = [c.get("name") for c in meeting.get("committees") or [] if c.get("name")]
    return {"chamber": chamber, "congress": congress, "event_id": str(event_id),
            "committee": names[0] if names else None, "committee_names": names,
            "occurs_at": meeting.get("date"), "status": meeting.get("meetingStatus"),
            "type": meeting.get("type"), "topic": (meeting.get("title") or "").strip() or None,
            "bill_ids": bill_ids(meeting)}


def run(data_dir, cache_file=None, days=60, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    congress = congress_for(now.date())
    cache = {}
    if cache_file and os.path.exists(cache_file):
        with open(cache_file) as f:
            cache = json.load(f)
    since = now - datetime.timedelta(days=days)
    for chamber in ("house", "senate"):
        upcoming = []
        for event_id, updated in changed_since(congress, chamber, since):
            key = f"{chamber}:{event_id}"
            entry = cache.get(key)
            if not entry or entry.get("updated") != updated:
                meeting = get(f"/committee-meeting/{congress}/{chamber}/{event_id}").get("committeeMeeting", {})
                entry = {"updated": updated, "record": record(meeting, chamber, congress, event_id)}
                cache[key] = entry
            meeting = entry["record"]
            when = meeting.get("occurs_at")
            if not when or (meeting.get("status") or "").lower() in DROPPED_STATUSES:
                continue
            if datetime.datetime.fromisoformat(when.replace("Z", "+00:00")) < now - datetime.timedelta(hours=3):
                continue
            upcoming.append(meeting)
        upcoming.sort(key=lambda m: m["occurs_at"])
        path = os.path.join(data_dir, f"committee_meetings_{chamber}.json")
        os.makedirs(data_dir, exist_ok=True)
        with open(path + ".tmp", "w") as out:
            json.dump(upcoming, out, indent=2, sort_keys=True)
        os.replace(path + ".tmp", path)
        print(f"[{chamber}] {len(upcoming)} upcoming meetings, {sum(len(m['bill_ids']) for m in upcoming)} bill links -> {path}")
    if cache_file:
        # Forget meetings long past, so the cache stays small.
        cutoff = (now - datetime.timedelta(days=days)).isoformat()
        cache = {k: v for k, v in cache.items() if (v["record"].get("occurs_at") or "") >= cutoff[:10]}
        with open(cache_file, "w") as out:
            json.dump(cache, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data_dir")
    parser.add_argument("--cache", help="Details cache (JSON), kept between runs")
    parser.add_argument("--days", type=int, default=60, help="Meetings updated in the last N days")
    args = parser.parse_args()
    run(args.data_dir, args.cache, args.days)
