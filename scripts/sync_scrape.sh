#!/usr/bin/env bash
# Sends a scrape's bills and roll calls (vote_event_*.json) to the app server's state-bills-data and rebuilds the
# state's catalog.
#
#   sync_scrape.sh partial <state> <label> <dir of bill_*.json>   a cut-off scrape's bills (adds, deletes nothing)
#   sync_scrape.sh final   <state> <label> <dir of bill_*.json>   a finished scrape (replaces; stamps .scraped_at)
#
# Remote when SYNC_HOST is set (ssh/rsync as ubuntu with SYNC_KEY, a key file);
# local otherwise (the job running on the app server itself).
set -euo pipefail
mode=$1 state=$2 label=$3 arg=$4
root=${STATE_BILLS_ROOT:-/home/ubuntu/state-bills-data}
app=${POPULIST_APP:-/home/ubuntu/microservice/Consumers/POP-U-LIST}
dest="$root/scrape/$label"

if [ -n "${SYNC_HOST:-}" ]; then
  ssh_opts="-i $SYNC_KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30 -o ServerAliveInterval=30"
  run() { ssh $ssh_opts "ubuntu@$SYNC_HOST" "$1"; }
  copy() { rsync -az -4 $1 --include='bill_*.json' --include='vote_event_*.json' --exclude='*' -e "ssh $ssh_opts" "$2/" "ubuntu@$SYNC_HOST:$dest/"; }
else
  run() { bash -c "$1"; }
  copy() { rsync -a $1 --include='bill_*.json' --include='vote_event_*.json' --exclude='*' "$2/" "$dest/"; }
fi

case "$mode" in
  partial|final)
    run "mkdir -p '$dest'"
    # The scraper names each file with a fresh id: a finished scrape's sync
    # clears the previous run's files; a cut-off one only adds (the catalog
    # keeps the copy of a bill with the latest action).
    if [ "$mode" = final ]; then copy --delete "$arg"; else copy "" "$arg"; fi
    stamp=""
    [ "$mode" = final ] && stamp="&& date -u +%Y-%m-%dT%H:%M:%SZ > '$dest/.scraped_at'"
    run "node '$app/stateBillCatalog.cjs' '$root' '$state' >/dev/null && flock -w 7200 '$root/legislative-mongo-index.lock' nice -n 19 node '$app/scripts/publish-legislative-index.cjs' ingest-state '${state^^}' $stamp"
    ;;
  *) echo "usage: sync_scrape.sh partial|final <state> <label> <dir>" >&2; exit 2 ;;
esac
