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
- **`bill-watcher.yml`** — clones the current and previous Congress' bill-status bulk
  data (GovInfo's `BILLSTATUS` collection) and syncs it to the server.
  Triggered by the watcher above, or manually via `workflow_dispatch`.
  `first_congress` can extend the backfill further; incremental runs reuse the cache.
- **`bill-text-watcher.yml`** — mirrors printed bill text separately so status
  refreshes do not interrupt a long text backfill. Its optional `congress` input
  supports historical backfills; daily runs follow the current Congress.
- **`rollcall-watcher.yml`** — clones roll-call vote data and sitting
  member profiles, and syncs them to the server. Runs on its own daily
  schedule (see the workflow file for why this one isn't event-triggered
  the same way yet).

Both sync workflows deploy their output to the server over SSH using
repo secrets (`SCYTALE_HOST`, `SCYTALE_SSH_KEY`) — no data or credentials
are ever committed to this repo.

## Historical archive

`legislation-archive.yml` backfills GovInfo bill status for Congresses 108–present
and printed bill text for Congresses 103–present. Dispatch `dataset=both` for the
whole modern archive, or narrow the Congress range to resume a subset. At most
two workers run concurrently. Monthly runs resume incomplete checkpoints;
completed historical snapshots are skipped unless `refresh_completed=true`.
The current Congress is refreshed when included.

Archives live in public GitHub Releases (`legislation-{congress}`), not Actions
cache, Git history, or additional AWS storage. Each immutable archive part is at
most 1 GiB and has a SHA-256 digest in its dataset manifest. Workers restore that
checkpoint after a bounded scrape window. Only after publication and the
necessary lookup/export steps succeed is the manifest marked complete. Rerun
failed jobs to resume an incomplete import. No existing archive parts are deleted.

The app server receives parsed bill JSON plus a small text-version sidecar,
without historical text ZIPs or full XML mirrors. Congresses 103–107 use public
MODS bill titles and version references for browsing; missing action, introduction,
and sponsorship records stay unknown. The app searches the whole imported
catalog by title or bill number and can filter by Congress. Historical text lookup bundles
are grouped by bill type and number (`text-{congress}-{type}-{number//100:04}.json.gz`).
These bundles retain each available print version and let the backend fetch a
small part of the archive on demand. PDFs, original package ZIPs and duplicate
HTML wrappers are excluded. The scraper's patch hook reuses verified extracted
checkpoints so omitting the original ZIP does not force repeat downloads.

Standard GitHub-hosted runners in this public repository remain free. Release
assets are subject to GitHub's hosting policies; each file remains below the
2 GiB release-asset limit. No paid cache expansion is required.
