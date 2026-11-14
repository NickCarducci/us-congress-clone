"""os-update, resumable: pages fetched by an earlier run (kept in --cachedir)
are served from the cache, while new requests keep the scraper's throttle.
Also tolerates a legislature listing a session the scraper doesn't know yet
(see _check_session_list_tolerant), fetches stateful pages fresh
(_request_fresh_when_stateful), and accepts action types Open States uses
before releasing them (below).

Open States reads its page cache only in --fastmode, which also turns off
throttling. scrapelib checks the cache before throttling, so allowing cache
reads alone resumes a cut-off scrape without hitting the legislature faster.
The workflow keys the cache by day, so a new day's run fetches fresh pages.

    python resumable_update.py <os-update arguments, including --cachedir>
"""
import sys

from openstates.scrape import base

_init = base.Scraper.__init__


def _resumable_init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    self.cache_write_only = False   # read pages cached by earlier runs; rpm unchanged


base.Scraper.__init__ = _resumable_init

_request = base.Scraper.request


def _request_fresh_when_stateful(self, method, url, *args, **kwargs):
    """The cache is keyed by address alone. A request that carries cookies, or
    repeats an address already fetched in this run, can get a different page
    than the cached one (Arizona sets its session by cookie, then serves the
    same /bills/ address with that session selected): fetch those fresh."""
    seen = self.__dict__.setdefault("_fetched_this_run", set())
    key = (str(method).upper(), str(url))
    stateful = bool(kwargs.get("cookies")) or key in seen
    seen.add(key)
    if not stateful or self.cache_write_only:
        return _request(self, method, url, *args, **kwargs)
    self.cache_write_only = True
    try:
        return _request(self, method, url, *args, **kwargs)
    finally:
        self.cache_write_only = False


base.Scraper.request = _request_fresh_when_stateful

# Bill action types the scrapers already use but Open States hasn't released in
# openstates-core yet (non-concurrence: in its repository since 2026-10-22,
# used by Massachusetts). The schema validates against this same list; once a
# release includes a type, nothing is added.
from openstates.data import common  # noqa: E402

for _classification in ("non-concurrence",):
    if _classification not in common.BILL_ACTION_CLASSIFICATIONS:
        common.BILL_ACTION_CLASSIFICATIONS.append(_classification)

import openstates.cli.update as update  # noqa: E402  (after the patch)
from openstates.exceptions import CommandError  # noqa: E402

_check_session_list = update.check_session_list


def _check_session_list_tolerant(juris):
    """A legislature's site lists its next session (every winter) before Open
    States adds it to the scraper, and os-update then refuses to run at all.
    The workflow always names the session to scrape, so an unknown session
    elsewhere on the site is only reported, not fatal. Every other check stands."""
    try:
        return _check_session_list(juris)
    except CommandError as error:
        if "were reported by" not in str(error):
            raise
        print(f"warning: {error} (scraping the requested session anyway)", file=sys.stderr, flush=True)
        return {s["identifier"] for s in juris.legislative_sessions if s.get("active")}


update.check_session_list = _check_session_list_tolerant
main = update.main

if __name__ == "__main__":
    sys.exit(main())
