"""A state's code, section by section, so a section a state bill cites opens
as its text in the app instead of a link out.

    python3 scripts/export_state_code.py <st> <out dir>
        -> <out>/t<file key>.json.gz (only units that changed), <out>/units.json, <out>/release.json

Resumable: <out>/units.json (pulled from the server before a run) says what's
been fetched; a run stops at CRAWL_BUDGET_MIN (default 50) or when a site
starts refusing, and the next run picks up there. See statecodes/crawl.py for
the crawler and statecodes/states.py for each jurisdiction and its terms.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statecodes.crawl import Crawl
from statecodes.states import STATES

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in STATES:
        sys.exit(__doc__ + "\nstates: " + " ".join(STATES))
    st, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    state = STATES[st]
    crawl = Crawl(out, spacing=state.spacing, timeout=state.timeout)
    meta = crawl.run(state.units(crawl), lambda src: state.parse(crawl, src))
    crawl.save()
    meta.update(source=state.source, exportedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(os.path.join(out, "release.json"), "w") as f:
        json.dump(meta, f)
    print(f"{st}: {meta['visited']}/{meta['units']} units this run, {meta['titles']} files, "
          f"{meta['sections']} sections" + (f"; stopped: {meta['stopped']}" if meta["stopped"] else ""), flush=True)
    if not meta["sections"]:
        sys.exit("nothing collected")
