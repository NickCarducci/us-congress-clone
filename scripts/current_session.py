"""Prints the state's current legislative session identifier, from the Open
States scraper's own metadata (legislative_sessions with start/end dates).

Run inside the scraper image, from its working directory:
    python current_session.py nj
See current() for the rule. (os-update's own default is the last listed
session, which can be next year's pre-filing session.)
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
    """Sessions are listed oldest to newest, and newer ones often lack dates.
    1. A special session running today (start and end both known).
    2. Else the last-listed regular session that hasn't started in the future
       (no start date counts as started). Skips next year's pre-filing session.
    3. Else "" (os-update's own default)."""
    def day(value):
        return datetime.date.fromisoformat(value[:10]) if value else None

    def started(s):
        return not day(s.get("start_date")) or day(s["start_date"]) <= today

    specials = [s for s in sessions if s.get("classification") == "special"
                and day(s.get("start_date")) and day(s.get("end_date"))
                and day(s["start_date"]) <= today <= day(s["end_date"])]
    if specials:
        return specials[-1]["identifier"]
    regular = [s for s in sessions if s.get("classification") != "special" and started(s)]
    return regular[-1]["identifier"] if regular else ""


if __name__ == "__main__":
    print(current(sessions_for(sys.argv[1].lower()), datetime.date.today()))
