"""os-update, resumable: pages fetched by an earlier run (kept in --cachedir)
are served from the cache, while new requests keep the scraper's throttle.

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

from openstates.cli.update import main  # noqa: E402  (after the patch)

if __name__ == "__main__":
    sys.exit(main())
