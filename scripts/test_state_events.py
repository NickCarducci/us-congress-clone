import datetime, importlib.util, json, pathlib, tempfile, unittest
from unittest import mock

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("state_events", here / "state_events.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

# Open States' /events shape (include=agenda), trimmed from a real NJ event.
EVENT = {"id": "ocd-event/559e", "name": "Meeting of the Senate Community and Urban Affairs Committee",
         "classification": "committee-meeting", "start_date": "2026-11-30T15:00:00+00:00", "status": "tentative",
         "deleted": False, "location": {"name": "Committee Room 6"},
         "agenda": [{"related_entities": [
             {"entity_type": "bill", "name": "SCR 96", "bill": {"identifier": "SCR 96", "session": "222"}},
             {"entity_type": "bill", "name": "A 462", "bill": {"identifier": "A 462", "session": "222"}},
             {"entity_type": "person", "name": "Someone"}]},
             {"related_entities": [{"entity_type": "bill", "bill": {"identifier": "SCR 96", "session": "222"}}]}]}
CANCELED = dict(EVENT, id="ocd-event/x", status="cancelled")


class StateEventsTests(unittest.TestCase):
    def test_hearings_with_bills_keyed_to_the_state_catalog(self):
        def get(path, pause, **params):
            self.assertEqual(params["require_bills"], "true")
            if params["jurisdiction"] == "tx":
                raise RuntimeError("Open States is down")
            events = [EVENT, dict(EVENT, id="ocd-event/dup"), CANCELED] if params["jurisdiction"] == "nj" else []
            return {"results": events, "pagination": {"max_page": 1}}
        with tempfile.TemporaryDirectory() as out, mock.patch.object(module, "get", get):
            failures = module.run(out, ["nj", "ca", "tx"], pause=0,
                                  now=datetime.datetime(2026, 11, 24, tzinfo=datetime.timezone.utc))
            nj = json.loads(pathlib.Path(out, "NJ.json").read_text())
            ca = json.loads(pathlib.Path(out, "CA.json").read_text())
            self.assertFalse(pathlib.Path(out, "TX.json").exists(), "a failed state keeps its last file")
        self.assertEqual(failures, 1)
        self.assertEqual(len(nj["events"]), 1, "canceled hearings and duplicates drop")
        self.assertEqual([b["id"] for b in nj["events"][0]["bills"]], ["NJ:222:SCR96", "NJ:222:A462"])
        self.assertEqual(ca["events"], [])


if __name__ == "__main__":
    unittest.main()
