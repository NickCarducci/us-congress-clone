import datetime
import importlib.util
import pathlib
import sys
import types
import unittest

# The picker imports openstates.scrape.State; stub it so the logic tests run anywhere.
stub = types.ModuleType("openstates.scrape"); stub.State = type("State", (), {})
sys.modules.setdefault("openstates", types.ModuleType("openstates")); sys.modules["openstates.scrape"] = stub
spec = importlib.util.spec_from_file_location("current_session", pathlib.Path(__file__).with_name("current_session.py"))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

FL = [
    {"identifier": "2025", "classification": "primary", "start_date": "2025-03-04", "end_date": "2025-05-02"},
    {"identifier": "2026", "classification": "primary", "start_date": "2026-01-13", "end_date": "2026-03-13"},
    {"identifier": "2026A", "classification": "special", "start_date": "2026-04-20", "end_date": "2026-04-24"},
    {"identifier": "2027", "classification": "primary", "start_date": "2027-03-02", "end_date": "2027-04-30"},
]
NJ = [{"identifier": "221", "classification": "primary", "start_date": "2024-01-09", "end_date": "2026-01-13"},
      {"identifier": "222", "classification": "primary", "start_date": "2026-01-13", "end_date": "2028-01-11"}]


class CurrentSession(unittest.TestCase):
    def test_between_sessions_takes_the_latest_regular_one_not_next_years_prefiling(self):
        self.assertEqual(module.current(FL, datetime.date(2026, 11, 13)), "2026")

    def test_the_regular_session_wins_over_a_running_special_one(self):
        self.assertEqual(module.current(FL, datetime.date(2026, 4, 22)), "2026")

    def test_a_special_session_only_without_a_regular_one(self):
        only_special = [{"identifier": "2026S1", "classification": "special",
                         "start_date": "2026-11-01", "end_date": "2026-11-30"}]
        self.assertEqual(module.current(only_special, datetime.date(2026, 11, 13)), "2026S1")

    def test_undated_newer_sessions_still_count_as_the_latest(self):
        tx = [{"identifier": "86", "classification": "primary", "start_date": "2019-01-08", "end_date": "2019-05-27"},
              {"identifier": "89", "classification": "primary"},
              {"identifier": "891", "classification": "special"}]
        self.assertEqual(module.current(tx, datetime.date(2026, 11, 13)), "89")

    def test_an_open_ended_special_session_is_not_taken_as_running(self):
        mn = [{"identifier": "2025-2026", "classification": "primary", "start_date": "2025-01-14"},
              {"identifier": "2025s1", "classification": "special", "start_date": "2025-06-09"}]
        self.assertEqual(module.current(mn, datetime.date(2026, 11, 13)), "2025-2026")

    def test_a_running_primary_wins(self):
        self.assertEqual(module.current(FL, datetime.date(2026, 2, 1)), "2026")
        self.assertEqual(module.current(NJ, datetime.date(2026, 11, 13)), "222")


if __name__ == "__main__":
    unittest.main()
