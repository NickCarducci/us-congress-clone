# us-congress-clone

Scheduled/event-triggered sync of **public** congressional data — bill
status, roll-call votes, and sitting-member profiles — from
[GovInfo](https://www.govinfo.gov/) and
[unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators)
to a private server, for use by [You In Politics](https://youinpolitics.com).

This repo intentionally contains **no proprietary application code** —
only data-sync workflows built on public government data sources and the
open-source [`unitedstates/congress`](https://github.com/unitedstates/congress)
scraper. It's public specifically so its GitHub Actions runs are
unmetered, which lets `govinfo-billstatus-watcher.yml` poll GovInfo's own
batch-completion feed every 15 minutes without consuming a private-repo
minutes quota.

## Workflows

- **`govinfo-billstatus-watcher.yml`** — polls GovInfo's
  [BILLSTATUS batch-notification RSS feed](https://www.govinfo.gov/rss/billstatus-batch.xml)
  every 15 minutes (matching the feed's own declared `<ttl>`) and triggers
  `bill-watcher.yml` only when a genuinely new batch has completed.
- **`bill-watcher.yml`** — clones the current Congress' bill-status bulk
  data (GovInfo's `BILLSTATUS` collection) and syncs it to the server.
  Triggered by the watcher above, or manually via `workflow_dispatch`.
- **`rollcall-watcher.yml`** — clones roll-call vote data and sitting
  member profiles, and syncs them to the server. Runs on its own daily
  schedule (see the workflow file for why this one isn't event-triggered
  the same way yet).

Both sync workflows deploy their output to the server over SSH using
repo secrets (`SCYTALE_HOST`, `SCYTALE_SSH_KEY`) — no data or credentials
are ever committed to this repo.
