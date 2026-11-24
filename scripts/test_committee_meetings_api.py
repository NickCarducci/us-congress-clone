import datetime, importlib.util, json, pathlib, tempfile, unittest
from unittest import mock

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("committee_meetings_api", here / "committee_meetings_api.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

NOW = datetime.datetime(2026, 11, 24, 22, 0, tzinfo=datetime.timezone.utc)

# The API's shapes (api.congress.gov/v3/committee-meeting), trimmed.
LISTS = {
    "house": [{"eventId": "119601", "updateDate": "2026-11-24T08:59:27Z"},
              {"eventId": "119700", "updateDate": "2026-11-23T10:00:00Z"},
              {"eventId": "119500", "updateDate": "2026-11-20T10:00:00Z"},
              {"eventId": "119400", "updateDate": "2026-11-20T10:00:00Z"}],
    "senate": [{"eventId": "338900", "updateDate": "2026-11-24T05:08:41Z"}],
}
DETAILS = {
    "119601": {"date": "2026-12-01T15:00:00Z", "meetingStatus": "Rescheduled", "type": "Hearing",
               "title": "A Climate of Bias ", "committees": [{"name": "House Judiciary Subcommittee on Courts"}]},
    "119700": {"date": "2026-12-02T15:00:00Z", "meetingStatus": "Scheduled", "type": "Markup",
               "title": "Markup of H.R. 9 and H.R. 10", "committees": [{"name": "House Energy and Commerce Committee"}],
               "relatedItems": {"bills": [{"congress": 119, "type": "HR", "number": "9"},
                                          {"congress": 119, "type": "HR", "number": "10"}]}},
    "119500": {"date": "2026-11-10T15:00:00Z", "meetingStatus": "Scheduled", "type": "Hearing", "title": "Past"},
    "119400": {"date": "2026-12-03T15:00:00Z", "meetingStatus": "Canceled", "type": "Hearing", "title": "Off"},
    "338900": {"date": "2026-12-01T19:30:00Z", "meetingStatus": "Scheduled", "type": "Hearing",
               "title": "Nominations", "committees": [{"name": "Senate Finance Committee"}],
               "relatedItems": {"bills": [{"congress": 119, "type": "S", "number": "5"}]}},
}


def fake_get(calls):
    def get(path, **params):
        calls.append(path)
        parts = path.strip("/").split("/")
        if len(parts) == 3:
            return {"committeeMeetings": LISTS[parts[2]]}
        return {"committeeMeeting": DETAILS[parts[3]]}
    return get


class CommitteeMeetingsAPITests(unittest.TestCase):
    def test_upcoming_meetings_in_the_scraper_task_shape(self):
        calls = []
        with tempfile.TemporaryDirectory() as data, mock.patch.object(module, "get", fake_get(calls)):
            cache = str(pathlib.Path(data, "cache.json"))
            module.run(data, cache, now=NOW)
            house = json.loads(pathlib.Path(data, "committee_meetings_house.json").read_text())
            senate = json.loads(pathlib.Path(data, "committee_meetings_senate.json").read_text())
            first = len(calls)
            # A second run fetches only the lists: nothing changed.
            module.run(data, cache, now=NOW)
            self.assertEqual(len(calls) - first, 2)
        self.assertEqual([m["event_id"] for m in house], ["119601", "119700"], "past and canceled meetings drop off")
        self.assertEqual(house[1]["bill_ids"], ["hr9-119", "hr10-119"])
        self.assertEqual(house[1]["committee"], "House Energy and Commerce Committee")
        self.assertEqual(house[0]["topic"], "A Climate of Bias")
        self.assertEqual(house[0]["occurs_at"], "2026-12-01T15:00:00Z")
        self.assertEqual(senate[0]["bill_ids"], ["s5-119"])


if __name__ == "__main__":
    unittest.main()
