"""Prints the state's current legislative session identifier, from the Open
States scraper's own metadata (legislative_sessions with start/end dates).

Run inside the scraper image, from its working directory:
    python current_session.py nj
Current = the primary session running today; else any session running today;
else the latest regular session that has started. (os-update's own default is the last
listed session, which can be next year's pre-filing session.)
"""
import datetime
import importlib
import sys

from openstates.scrape import State


def sessions_for(abbr):
    module = importlib.import_module(f"scrapers.{abbr}")
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, State) and value is not State:
            return value.legislative_sessions
    raise SystemExit(f"no State class in scrapers.{abbr}")


def current(sessions, today):
    def day(value):
        return datetime.date.fromisoformat(value[:10]) if value else None

    running = [s for s in sessions
               if day(s.get("start_date")) and day(s["start_date"]) <= today
               and (not day(s.get("end_date")) or today <= day(s["end_date"]))]
    primary = [s for s in running if s.get("classification") == "primary"]
    if primary or running:
        return max(primary or running, key=lambda s: s["start_date"])["identifier"]
    started = [s for s in sessions if day(s.get("start_date")) and day(s["start_date"]) <= today]
    regular = [s for s in started if s.get("classification") == "primary"]
    pool = regular or started
    return max(pool, key=lambda s: s["start_date"])["identifier"] if pool else ""


if __name__ == "__main__":
    print(current(sessions_for(sys.argv[1].lower()), datetime.date.today()))
