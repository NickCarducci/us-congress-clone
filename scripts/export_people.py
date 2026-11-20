"""Each state legislator's names and Open States person id, for matching the
daily scrape's roll calls (which name voters but carry no id) to the people the
app follows. From openstates/people (CC0-1.0), data/<st>/legislature/*.yml.

    python3 export_people.py <people checkout> <out dir>
    -> <out>/<ST>.json  [{"id", "names": [...], "chambers": [...]}]

Every legislature member the repository lists, sitting or retired (a retired
member's old votes still need their name), with all the names they go by.
"""
import json, os, sys, glob
import yaml

def main(src, out):
    os.makedirs(out, exist_ok=True)
    for state_dir in sorted(glob.glob(os.path.join(src, "data", "*"))):
        st = os.path.basename(state_dir)
        people = []
        for sub in ("legislature", "retired"):
            for path in sorted(glob.glob(os.path.join(state_dir, sub, "*.yml"))):
                with open(path) as f:
                    p = yaml.safe_load(f) or {}
                chambers = sorted({r.get("type") for r in p.get("roles") or []
                                   if r.get("type") in ("upper", "lower", "legislature")})
                if not p.get("id") or not chambers:
                    continue
                names = [p.get("name")] + [o.get("name") for o in p.get("other_names") or []]
                people.append({"id": p["id"], "names": sorted({n for n in names if n}),
                               "family": p.get("family_name"), "chambers": chambers,
                               "current": sub == "legislature"})
        if people:
            with open(os.path.join(out, f"{st.upper()}.json"), "w") as f:
                json.dump(people, f, separators=(",", ":"), sort_keys=True)
            print(st, len(people))

if __name__ == "__main__":
    main(*sys.argv[1:3])
