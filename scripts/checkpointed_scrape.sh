#!/usr/bin/env bash
# Runs a scrape with checkpoints: at FIRST_CHECK seconds (20 minutes) and then
# every EVERY seconds (an hour), what's been scraped so far is checked
# (check_scrape.py). Proper: it's synced to the app server (partial) and the
# scrape goes on. Not proper: the scrape is stopped and fails, and the health
# record says why. At DEADLINE seconds the scrape stops itself, syncs what it
# has and exits 124, so a pass cut off by the job's time limit still lands and
# the next pass resumes from the cached pages.
#
#   checkpointed_scrape.sh <state> <label> <out dir> <session> <container> -- <docker run …>
#
# The docker command must name its container <container>. Exit: 0 finished
# (not yet synced: the caller runs sync_scrape.sh final), 124 cut off, 3 a
# check failed, else the scraper's own failure. Health goes to the server each time.
set -uo pipefail
state=$1 label=$2 out=$3 session=$4 container=$5
shift 5; [ "${1:-}" = "--" ] && shift
here="$(cd "$(dirname "$0")" && pwd)"
first=${FIRST_CHECK:-1200} every=${EVERY:-3600} deadline=${DEADLINE:-19800}
log=${SCRAPE_LOG:-scrape.log}

health() {   # phase message [check json]
  local check=${3:-'{}'}
  local json
  json=$(python3 -c 'import json,sys; c=json.loads(sys.argv[5]); print(json.dumps({"state": sys.argv[1], "label": sys.argv[2], "phase": sys.argv[3], "message": sys.argv[4], "at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), **c}))' \
    "$state" "$label" "$1" "$2" "$check")
  echo "health: $json"
  "$here/sync_scrape.sh" health "$state" "$label" "$json" || echo "warning: couldn't record health" >&2
}

# Checks what's there; proper and non-empty is synced (partial). Returns 1 if not proper.
checkpoint() {
  mkdir -p "$out"
  local result
  result=$(python3 "$here/check_scrape.py" "$out" ${session:+--session "$session"})
  local proper=$?
  echo "checkpoint after $((SECONDS / 60)) min: $result"
  if [ $proper -ne 0 ]; then
    health failed "what was scraped isn't proper bill data" "$result"
    return 1
  fi
  if [ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["bills"])' "$result")" -gt 0 ]; then
    "$here/sync_scrape.sh" partial "$state" "$label" "$out" || echo "warning: partial sync failed" >&2
  fi
  health "${1:-checkpoint}" "${2:-scraping}" "$result"
}

stop_scraper() {
  docker stop -t 30 "$container" >/dev/null 2>&1
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
}

"$@" > "$log" 2>&1 &
pid=$!
next=$first
status=""
while kill -0 "$pid" 2>/dev/null; do
  sleep 15
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "stopping at the deadline ($((deadline / 60)) min); the next pass resumes"
    stop_scraper
    checkpoint cut-off "stopped at the time limit; the next pass resumes from cached pages" || true
    status=124; break
  fi
  if [ "$SECONDS" -ge "$next" ]; then
    if ! checkpoint; then
      stop_scraper
      status=3; break
    fi
    next=$((next + every))
  fi
done
if [ -z "$status" ]; then
  wait "$pid"; status=$?
  if [ $status -eq 0 ]; then
    result=$(python3 "$here/check_scrape.py" "$out" ${session:+--session "$session"}) || {
      echo "final check: $result"; health failed "the finished scrape isn't proper bill data" "$result"; status=3; }
    [ $status -eq 0 ] && health finished "finished; syncing" "$result"
  else
    # The scraper itself failed: keep whatever proper bills it got, and say so.
    checkpoint failed "the scraper exited with $status" || true
  fi
fi
tail -n 200 "$log"
exit $status
