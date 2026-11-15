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

# Only when Open States has seen a change since the last finished scrape (less
# 6 hours' overlap), the same check state-bill-watcher.yml's plan job makes.
# No key, no earlier scrape, or a failed check: scrape anyway.
root=${STATE_BILLS_ROOT:-/home/ubuntu/state-bills-data}
env_file=${OPEN_STATES_ENV_FILE:-$HOME/.config/populist/openstates.env}
[ -r "$env_file" ] && { set -a; . "$env_file"; set +a; }
if [ -n "${OPEN_STATES_KEY:-}" ] && [ -f "$root/scrape/$state/.scraped_at" ] && [ ! -f "$work/.unfinished" ]; then
  changed=$(python3 - "$here" "$state" "$(cat "$root/scrape/$state/.scraped_at")" <<'PY' || echo error
import datetime, sys
sys.path.insert(0, sys.argv[1])
import plan_states
since = datetime.datetime.fromisoformat(sys.argv[3].replace("Z", "+00:00")) - plan_states.OVERLAP
print(plan_states.updated_count(sys.argv[2], since, __import__("os").environ["OPEN_STATES_KEY"]))
PY
)
  if [ "$changed" = 0 ]; then
    echo "$(date -u +%FT%TZ) $state unchanged since $(cat "$root/scrape/$state/.scraped_at"); skipped"
    exit 0
  fi
  echo "changes since the last scrape: $changed"
fi

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
  rm -f "$work/.unfinished"
else
  date -u +%FT%TZ > "$work/.unfinished"   # the next run resumes, change or not
fi
echo "$(date -u +%FT%TZ) $state done ($code)"
exit $code
