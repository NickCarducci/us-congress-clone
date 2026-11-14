#!/usr/bin/env bash
# Scrapes one state on the app server, for legislatures that refuse GitHub's
# runners but answer the server (Texas: its FTP resets GitHub's connections).
# Daily from cron on the server (see POP-U-LIST OPS.md), with a clone of this
# repository kept current by the same cron line.
#
#   server_scrape.sh <state> [rpm]
#
# Same scraper and checkpoints as state-bill-watcher.yml: Open States' published
# image (openstates/scrapers), this repository's resumable_update.py, and
# checkpointed_scrape.sh syncing to the local state-bills-data. The page cache
# persists here: an unfinished run's next pass resumes from it; a finished one's
# next pass starts fresh. Output and errors go to the cron log.
set -euo pipefail
state=$1 rpm=${2:-60}
here="$(cd "$(dirname "$0")" && pwd)"
image=${SCRAPER_IMAGE:-openstates/scrapers:latest}
work="${SERVER_SCRAPE_WORK:-$HOME/state-scrape-work}/$state"
mkdir -p "$work"
exec 9> "$work/.lock"
flock -n 9 || { echo "$(date -u +%FT%TZ) $state already running"; exit 0; }
echo "$(date -u +%FT%TZ) $state start"

docker pull -q "$image" >/dev/null
docker image prune -f >/dev/null   # the previous day's image, once replaced

# A finished last run: start fresh. Unfinished: keep its pages to resume.
if [ -f "$work/.finished" ]; then rm -rf "$work/cache" "$work/.finished"; fi
rm -rf "$work/out"; mkdir -p "$work/out" "$work/cache"

py() { docker run --rm "$@"; }
session=$(py -v "$here:/tools:ro" -w /opt/openstates/openstates \
  -e DC_API_KEY=unused -e NEW_YORK_API_KEY=unused -e INDIANA_API_KEY=unused \
  -e PYTHONPATH=/opt/openstates/openstates:/opt/openstates/openstates/scrapers --entrypoint python \
  "$image" /tools/current_session.py "$state")
echo "session: ${session:-(scraper default)}"

name="scrape-$state"
docker rm -f "$name" >/dev/null 2>&1 || true
cd "$work"
code=0
DEADLINE=${DEADLINE:-72000} "$here/checkpointed_scrape.sh" "$state" "$state" "out/$state" "$session" "$name" -- \
  docker run --rm --name "$name" -v "$work/out:/out" -v "$work/cache:/cache" -v "$here:/tools:ro" \
    -w /opt/openstates/openstates -e PYTHONPATH=/opt/openstates/openstates:/opt/openstates/openstates/scrapers \
    --entrypoint python "$image" /tools/resumable_update.py "$state" bills ${session:+session=$session} \
    --scrape --nonstrict --datadir /out --cachedir /cache --rpm "$rpm" --retries 5 --retry_wait 30 || code=$?

if [ $code -eq 0 ]; then
  "$here/sync_scrape.sh" final "$state" "$state" "out/$state"
  date -u +%FT%TZ > "$work/.finished"
fi
echo "$(date -u +%FT%TZ) $state done ($code)"
exit $code
