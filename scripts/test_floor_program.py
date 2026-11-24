import importlib.util, json, pathlib, tempfile, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("floor_program", here / "floor_program.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

# The Record's real text for Nov 19, 2026: nominations only, no bills.
REAL = (here / "fixtures" / "next_meeting_2026-11-19.txt").read_text()

# A program that names bills (the shape the Daily Digest uses for them).
WITH_BILLS = """
                       Next Meeting of the SENATE
                      12 noon, Monday, December 14

                             Senate Chamber
Program for Monday: Senate will resume consideration of H.R. 4016,
Department of Defense Appropriations Act, and vote on passage thereof at
5:30 p.m.
  Following disposition of H.R. 4016, Senate will begin consideration of
S.J. Res. 12, providing for congressional disapproval of a rule.

              Next Meeting of the HOUSE OF REPRESENTATIVES
                    9 a.m., Tuesday, December 15

                             House Chamber
Program for Tuesday: Consideration of H.R. 5101--Rural Broadband Act
(Subject to a Rule). Consideration of measures under suspension of the
Rules, including H. Res. 77.
_______________________________________________________________________
"""


class FloorProgramTests(unittest.TestCase):
    def test_real_record_has_meeting_times_and_no_bills(self):
        chambers = module.parse_next_meetings(REAL, "CREC-2026-11-19", 119)
        self.assertEqual(chambers["senate"]["meets_at"], "2026-11-20T10:00:00-05:00")
        self.assertEqual(chambers["house"]["meets_at"], "2026-11-20T10:30:00-05:00")
        self.assertIn("Bennett", chambers["senate"]["program"])
        self.assertEqual(chambers["senate"]["items"], [])
        self.assertIn("Pro Forma", chambers["house"]["program"])

    def test_bills_in_a_program_are_ids_with_their_day(self):
        chambers = module.parse_next_meetings(WITH_BILLS, "CREC-2026-12-11", 119)
        senate = chambers["senate"]
        self.assertEqual(senate["meets_at"], "2026-12-14T12:00:00-05:00")
        self.assertEqual([i["bill_id"] for i in senate["items"]], ["hr4016-119", "sjres12-119"])
        self.assertTrue(all(i["chamber"] == "senate" and i["scheduled_for"] == "2026-12-14" for i in senate["items"]))
        self.assertIn("vote on passage", senate["items"][0]["description"])
        house = chambers["house"]
        self.assertEqual(house["meets_at"], "2026-12-15T09:00:00-05:00")
        self.assertEqual([i["bill_id"] for i in house["items"]], ["hr5101-119", "hres77-119"])

    def test_daylight_saving_and_year_end(self):
        self.assertEqual(module.meeting_time("2 p.m., Monday, June 1", __import__("datetime").date(2026, 5, 29))[1],
                         "2026-06-01T14:00:00-04:00")
        # A late-December Record scheduling January.
        self.assertEqual(module.meeting_time("10 a.m., Tuesday, January 5", __import__("datetime").date(2026, 12, 31))[0],
                         "2027-01-05")

    def test_run_reads_the_mirrored_package_and_writes_one_file_per_record(self):
        import datetime, zipfile
        with tempfile.TemporaryDirectory() as data:
            for day, text in [("2026-12-10", REAL), ("2026-12-11", WITH_BILLS)]:
                package = pathlib.Path(data, "govinfo", "CREC", day)
                package.mkdir(parents=True)
                with zipfile.ZipFile(package / "package.zip", "w") as archive:
                    archive.writestr(f"CREC-{day}/html/CREC-{day}-pt1-PgS7000.htm", "<pre>Senate floor</pre>")
                    archive.writestr(f"CREC-{day}/html/CREC-{day}-pt1-PgD1200.htm", "<pre>Highlights</pre>")
                    archive.writestr(f"CREC-{day}/html/CREC-{day}-pt1-PgD1201-3.htm", "<pre>" + text + "</pre>")
            path = module.run(data, today=datetime.date(2026, 12, 12))
            saved = json.loads(pathlib.Path(path).read_text())
            # Too old to count.
            self.assertIsNone(module.run(data, today=datetime.date(2027, 1, 30)))
        self.assertEqual(pathlib.Path(path).name, "2026-12-11.json", "the newest Record")
        self.assertEqual(saved["record"], "CREC-2026-12-11")
        self.assertEqual(saved["congress"], 119)
        self.assertEqual(len(saved["chambers"]["senate"]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
