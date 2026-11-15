# Overrides openstates-scrapers' scrapers/vi/__init__.py (copied in by
# state-bill-watcher.yml): the session list comes from the rebuilt tracker
# site, not its retired JSON API on port 8082. Otherwise upstream's file.
# from utils import url_xpath
from openstates.scrape import State

from .bills import VIBillScraper
from .events import VIEventScraper
import re

import requests


class VirginIslands(State):
    scrapers = {
        "bills": VIBillScraper,
        "events": VIEventScraper,
    }
    legislative_sessions = [
        {
            "_scraped_name": "30",
            "classification": "primary",
            "identifier": "30",
            "name": "2013-2014 Regular Session",
            "start_date": "2013-01-09",
            "end_date": "2014-12-31",
        },
        {
            "_scraped_name": "31",
            "classification": "primary",
            "identifier": "31",
            "name": "2015-2016 Regular Session",
            "start_date": "2015-01-09",
            "end_date": "2016-12-31",
        },
        {
            "_scraped_name": "32",
            "classification": "primary",
            "identifier": "32",
            "name": "2017-2018 Regular Session",
            "start_date": "2017-01-09",
            "end_date": "2018-12-31",
        },
        {
            "_scraped_name": "33",
            "classification": "primary",
            "identifier": "33",
            "name": "2019-2020 Regular Session",
            "start_date": "2019-01-09",
            "end_date": "2020-12-31",
        },
        {
            "_scraped_name": "34",
            "classification": "primary",
            "identifier": "34",
            "name": "2021-2022 Regular Session",
            "start_date": "2021-01-09",
            "end_date": "2022-12-31",
        },
        {
            "_scraped_name": "35",
            "classification": "primary",
            "identifier": "35",
            "name": "2023-2024 Regular Session",
            "start_date": "2023-01-09",
            "end_date": "2024-12-31",
            "active": False,
        },
        {
            "_scraped_name": "36",
            "classification": "primary",
            "identifier": "36",
            "name": "2025-2026 Regular Session",
            "start_date": "2025-01-09",
            "end_date": "2026-12-31",
            "active": True,
        },
    ]
    ignored_scraped_sessions = ["21", "22", "23", "24", "25", "26", "27", "28", "29"]

    def get_session_list(self):
        # The tracker's old JSON API (port 8082) is gone; its site names the
        # current Legislature ("36th Legislature of United States Virgin Islands").
        page = requests.get("https://billtracking.legvi.org/", timeout=60).text
        current = re.search(r"(\d+)(?:st|nd|rd|th) Legislature of", page)
        known = {s["_scraped_name"] for s in self.legislative_sessions} | set(self.ignored_scraped_sessions)
        return sorted(known | ({current.group(1)} if current else set()), key=int)
