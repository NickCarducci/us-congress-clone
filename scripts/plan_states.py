"""Builds state-bill-watcher.yml's job matrix from state-sources.json: one job
per scraped state, or one per chamber for a split state. States left to the
API, and key-holding states whose secret isn't set, get no job (the app
server's Open States API watcher keeps covering them).

A state is only scraped when something changed: with OPEN_STATES_KEY set, one
Open States request per state (bills updated_since its last finished scrape,
less a few hours' overlap) decides. A state with no finished scrape yet, or
whose check fails, is scraped. Naming states by hand skips the check.

    python3 plan_states.py <state-sources.json> [states, e.g. "nj,pa"] [scraped_at.txt]
Secrets present are named in HAVE_SECRETS (comma list) by the workflow.
scraped_at.txt: "<label> <ISO time>" per line, each job's last finished scrape.
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OVERLAP = datetime.timedelta(hours=6)   # Open States can see a change after we scraped past it
PAUSE = 2.0                             # seconds between requests (the free tier is rate-limited)


def plan(config, only=(), have_secrets=()):
    defaults = config.get("defaults", {})
    jobs, skipped = [], []
    for state, overrides in sorted(config["states"].items()):
        if only and state not in only:
            continue
        settings = {**defaults, **{k: v for k, v in overrides.items() if not k.startswith("_")}}
        if settings["source"] != "scraper":
            skipped.append(f"{state}: {settings['source']}")
            continue
        secret = settings.get("secret")
        if secret and secret not in have_secrets:
            skipped.append(f"{state}: needs {secret}")
            continue
        for chamber in (["upper", "lower"] if settings["split"] else [""]):
            jobs.append({"state": state, "chamber": chamber, "rpm": settings["rpm"], "secret": secret or "",
                         "scraper": settings.get("scraper", "bills")})
    return jobs, skipped


def parse_marks(text):
    marks = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                marks[parts[0]] = datetime.datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
            except ValueError:
                pass
    return marks


def jurisdiction(state):
    kind = "district" if state == "dc" else "state"
    return f"ocd-jurisdiction/country:us/{kind}:{state}/government"


def updated_count(state, since, api_key):
    """Bills Open States has seen change in `state` since `since`."""
    query = urllib.parse.urlencode({"jurisdiction": jurisdiction(state), "per_page": 1,
                                    "updated_since": since.strftime("%Y-%m-%dT%H:%M:%S")})
    request = urllib.request.Request(f"https://v3.openstates.org/bills?{query}", headers={"X-API-Key": api_key})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["pagination"]["total_items"]


def gate(jobs, marks, check):
    """Keeps the jobs of states that changed. check(state, since) -> count, or
    raises. Returns (kept jobs, report lines)."""
    by_state = {}
    for job in jobs:
        by_state.setdefault(job["state"], []).append(job)
    kept, report = [], []
    for state, state_jobs in by_state.items():
        times = [marks.get(job["state"] + job["chamber"]) for job in state_jobs]
        if any(t is None for t in times):
            kept += state_jobs
            report.append(f"{state}: scraped (no finished scrape yet)")
            continue
        since = min(times) - OVERLAP
        try:
            count = check(state, since)
        except Exception as error:   # fail open: a missed check scrapes
            kept += state_jobs
            report.append(f"{state}: scraped (check failed: {error})")
            continue
        if count:
            kept += state_jobs
            report.append(f"{state}: scraped ({count} bills updated since {since:%Y-%m-%d %H:%M} UTC)")
        else:
            report.append(f"{state}: unchanged since {since:%Y-%m-%d %H:%M} UTC, skipped")
    return kept, report


if __name__ == "__main__":
    config = json.load(open(sys.argv[1]))
    only = {s.strip().lower() for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()}
    have = {s for s in os.environ.get("HAVE_SECRETS", "").split(",") if s}
    jobs, skipped = plan(config, only, have)
    for line in skipped:
        print(f"skipped {line}", file=sys.stderr)
    api_key = os.environ.get("OPEN_STATES_KEY", "")
    marks_file = sys.argv[3] if len(sys.argv) > 3 else ""
    if api_key and not only and marks_file and os.path.exists(marks_file):
        def check(state, since):
            time.sleep(PAUSE)
            return updated_count(state, since, api_key)
        jobs, report = gate(jobs, parse_marks(open(marks_file).read()), check)
        for line in report:
            print(line, file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as out:
                out.write("### Change check (Open States updated_since)\n\n" + "\n".join(f"- {l}" for l in report) + "\n")
    elif not only:
        print("no change check (OPEN_STATES_KEY not set or no scrape times): scraping every state", file=sys.stderr)
    # Empty when nothing changed anywhere: the workflow then skips the scrape job.
    print(json.dumps({"include": jobs}))
