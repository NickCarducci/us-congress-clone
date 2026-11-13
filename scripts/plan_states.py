"""Builds state-bill-watcher.yml's job matrix from state-sources.json: one job
per scraped state, or one per chamber for a split state. States left to the
API, and key-holding states whose secret isn't set, get no job (the app
server's Open States API watcher keeps covering them).

    python3 plan_states.py <state-sources.json> [states, e.g. "nj,pa"]
Secrets present are named in HAVE_SECRETS (comma list) by the workflow.
"""
import json
import os
import sys


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
            jobs.append({"state": state, "chamber": chamber, "rpm": settings["rpm"], "secret": secret or ""})
    return jobs, skipped


if __name__ == "__main__":
    config = json.load(open(sys.argv[1]))
    only = {s.strip().lower() for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()}
    have = {s for s in os.environ.get("HAVE_SECRETS", "").split(",") if s}
    jobs, skipped = plan(config, only, have)
    for line in skipped:
        print(f"skipped {line}", file=sys.stderr)
    if not jobs:
        raise SystemExit("No states to scrape")
    print(json.dumps({"include": jobs}))
