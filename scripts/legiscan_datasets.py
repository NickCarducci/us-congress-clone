"""LegiScan's weekly session datasets as the state bills' base layer.

    python3 legiscan_datasets.py <hashes.json> <out-dir> [--states nj,pa]

Asks getDatasetList once (one query), then getDataset only for current
sessions whose dataset_hash changed since hashes.json (one query each), and
writes each as <out-dir>/<st>/<st>_ls<session_id>.json.gz: a JSON object
{"legiscan": {session meta}, "bills": [...]}, the bills in the shape of
Open States' session JSON (identifier, title, legislative_session, chamber,
classification, subject, actions, sponsors, abstracts, sources), so the app's
catalog reads them like the Open States bulk download. hashes.json is
rewritten with the new hashes. LEGISCAN_API_KEY comes from the environment.
Prints one line per session fetched and the queries spent.
"""
import argparse
import base64
import datetime
import gzip
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile

API = "https://api.legiscan.com/"
STATES = {"ak", "al", "ar", "az", "ca", "co", "ct", "dc", "de", "fl", "ga", "hi", "ia", "id", "il", "in",
          "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo", "ms", "mt", "nc", "nd", "ne", "nh", "nj",
          "nm", "nv", "ny", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa",
          "wi", "wv", "wy"}
# LegiScan's state_id: the states alphabetically by name (CA 5 and MD 20 in its
# manual), then DC (51; US Congress is 52). Each ZIP also names its state in
# its paths, which is what the file is written under.
STATE_IDS = ["al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks",
             "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny",
             "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
             "wi", "wy", "dc"]
# body: S Senate (upper); H House, A Assembly (lower); J joint.
CHAMBERS = {"S": "upper", "H": "lower", "A": "lower", "J": "legislature"}


def call(key, **params):
    query = urllib.parse.urlencode({"key": key, **params})
    with urllib.request.urlopen(f"{API}?{query}", timeout=300) as response:
        data = json.load(response)
    if data.get("status") != "OK":
        raise RuntimeError(f"LegiScan {params.get('op')}: {data.get('alert', {}).get('message') or data.get('status')}")
    return data


def state_of(dataset):
    sid = int(dataset["state_id"])
    return STATE_IDS[sid - 1] if 1 <= sid <= len(STATE_IDS) else None


def is_current(dataset, today):
    return int(dataset.get("year_end") or 0) >= today.year - 1


def to_open_states(bill, session_name):
    """One LegiScan bill as an Open States session-JSON bill."""
    history = bill.get("history") or []
    description = (bill.get("description") or "").strip()
    sources = [{"url": u} for u in (bill.get("state_link"), bill.get("url")) if u]
    return {
        "identifier": bill.get("bill_number"),
        "title": bill.get("title"),
        "legislative_session": session_name,
        "chamber": CHAMBERS.get(bill.get("body")),
        "from_organization_name": None,
        "classification": [],
        "subject": [s["subject_name"] for s in bill.get("subjects") or [] if s.get("subject_name")],
        "actions": [{"date": a.get("date"), "description": a.get("action"), "order": i,
                     "organization__name": None} for i, a in enumerate(history) if a.get("date")],
        "sponsors": [{"name": s.get("name"), "primary": int(s.get("sponsor_type_id") or 0) == 1}
                     for s in bill.get("sponsors") or [] if s.get("name")],
        "abstracts": [{"abstract": description}] if description and description != bill.get("title") else [],
        "sources": sources,
    }


def bills_from_zip(raw):
    """(state from the ZIP's paths, every bill/*.json in file order)."""
    bills, states = [], set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in sorted(archive.namelist()):
            if re.search(r"/bill/[^/]+\.json$", name):
                bill = json.loads(archive.read(name))["bill"]
                bills.append(bill)
                if bill.get("state"):
                    states.add(str(bill["state"]).lower())
    return (states.pop() if len(states) == 1 else None), bills


def write_session(out, state, dataset, bills):
    meta = {k: dataset.get(k) for k in ("session_id", "session_name", "session_title", "year_start", "year_end",
                                        "special", "dataset_hash", "dataset_date")}
    payload = {"legiscan": meta, "bills": [to_open_states(b, dataset["session_name"]) for b in bills]}
    path = os.path.join(out, state, f"{state}_ls{dataset['session_id']}.json.gz")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as handle:
        handle.write(text)
    return len(payload["bills"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("hashes")
    parser.add_argument("out")
    parser.add_argument("--states", default="")
    args = parser.parse_args()
    key = os.environ["LEGISCAN_API_KEY"]
    only = {s.strip().lower() for s in args.states.split(",") if s.strip()}
    try:
        hashes = json.load(open(args.hashes))
    except (OSError, ValueError):
        hashes = {}
    today = datetime.date.today()
    queries = 1
    listing = call(key, op="getDatasetList")["datasetlist"]
    for dataset in listing:
        state = state_of(dataset)
        if state not in STATES or (only and state not in only) or not is_current(dataset, today):
            continue
        sid = str(dataset["session_id"])
        if hashes.get(sid) == dataset["dataset_hash"]:
            continue
        archive = call(key, op="getDataset", id=sid, access_key=dataset["access_key"])["dataset"]
        queries += 1
        named, bills = bills_from_zip(base64.b64decode(archive["zip"]))
        if named and named != state:
            print(f"warning: session {sid} listed as {state}, its bills say {named}", flush=True)
            state = named
        if state not in STATES:
            continue
        count = write_session(args.out, state, dataset, bills)
        hashes[sid] = dataset["dataset_hash"]
        print(f"{state}\t{dataset['session_name']}\t{count}", flush=True)
    with open(args.hashes, "w") as handle:
        json.dump(hashes, handle, indent=0, sort_keys=True)
    print(f"QUERIES\t{queries}")


if __name__ == "__main__":
    main()
