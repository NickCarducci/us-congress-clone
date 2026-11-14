#!/usr/bin/env bash
# Sends a scrape's bills to the app server's state-bills-data and rebuilds the
# state's catalog; or records the scrape's health there.
#
#   sync_scrape.sh partial <state> <label> <dir of bill_*.json>   what's scraped so far (adds, deletes nothing)
#   sync_scrape.sh final   <state> <label> <dir of bill_*.json>   a finished scrape (replaces; stamps .scraped_at)
#   sync_scrape.sh health  <state> <label> <json>                 writes scrape/<label>/.health.json
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
  copy() { rsync -az -4 $1 --include='bill_*.json' --exclude='*' -e "ssh $ssh_opts" "$2/" "ubuntu@$SYNC_HOST:$dest/"; }
  put() { ssh $ssh_opts "ubuntu@$SYNC_HOST" "cat > '$1'"; }
else
  run() { bash -c "$1"; }
  copy() { rsync -a $1 --include='bill_*.json' --exclude='*' "$2/" "$dest/"; }
  put() { cat > "$1"; }
fi

case "$mode" in
  partial|final)
    run "mkdir -p '$dest'"
    # The scraper names each file with a fresh id: a finished scrape's sync
    # clears the previous run's files; a partial one only adds (the catalog
    # keeps the copy of a bill with the latest action).
    if [ "$mode" = final ]; then copy --delete "$arg"; else copy "" "$arg"; fi
    stamp=""
    [ "$mode" = final ] && stamp="&& date -u +%Y-%m-%dT%H:%M:%SZ > '$dest/.scraped_at'"
    run "node '$app/stateBillCatalog.cjs' '$root' '$state' >/dev/null $stamp"
    ;;
  health)
    run "mkdir -p '$dest'"
    printf '%s\n' "$arg" | put "$dest/.health.json"
    ;;
  *) echo "usage: sync_scrape.sh partial|final|health <state> <label> <arg>" >&2; exit 2 ;;
esac
