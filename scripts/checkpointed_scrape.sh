#!/usr/bin/env bash
# Runs a scrape with one early check: at FIRST_CHECK seconds (20 minutes) a
# sample of the newest bills scraped (check_scrape.py --sample 50) must be
# proper bill data, or the scrape is stopped and fails. At DEADLINE seconds the
# scrape stops itself and syncs what it has (partial) and exits 124, so a pass
# cut off by the job's time limit still lands and the next pass resumes from
# the cached pages.
#
#   checkpointed_scrape.sh <state> <label> <out dir> <session> <container> -- <docker run …>
#
# The docker command must name its container <container>. Exit: 0 finished
# (not yet synced: the caller runs sync_scrape.sh final), 124 cut off, 3 the
# check failed, else the scraper's own failure.
set -uo pipefail
state=$1 label=$2 out=$3 session=$4 container=$5
shift 5; [ "${1:-}" = "--" ] && shift
here="$(cd "$(dirname "$0")" && pwd)"
first=${FIRST_CHECK:-1200} deadline=${DEADLINE:-19800}
log=${SCRAPE_LOG:-scrape.log}

proper() {
  mkdir -p "$out"
  local result
  result=$(python3 "$here/check_scrape.py" "$out" --sample 50 ${session:+--session "$session"})
  local ok=$?
  echo "check after $((SECONDS / 60)) min: $result"
  [ $ok -eq 0 ] || echo "::error::$state $label: what was scraped isn't proper bill data: $result"
  return $ok
}

stop_scraper() {
  docker stop -t 30 "$container" >/dev/null 2>&1
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
}

"$@" > "$log" 2>&1 &
pid=$!
checked=""
status=""
while kill -0 "$pid" 2>/dev/null; do
  sleep 15
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "stopping at the deadline ($((deadline / 60)) min); the next pass resumes"
    stop_scraper
    proper && "$here/sync_scrape.sh" partial "$state" "$label" "$out"
    status=124; break
  fi
  if [ -z "$checked" ] && [ "$SECONDS" -ge "$first" ]; then
    checked=1
    proper || { stop_scraper; status=3; break; }
  fi
done
if [ -z "$status" ]; then
  wait "$pid"; status=$?
  [ $status -eq 0 ] && { proper || status=3; }
fi
tail -n 200 "$log"
exit $status
