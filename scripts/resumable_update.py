"""os-update, resumable: pages fetched by an earlier run (kept in --cachedir)
are served from the cache, while new requests keep the scraper's throttle.
Also tolerates a legislature listing a session the scraper doesn't know yet
(see _check_session_list_tolerant).

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
