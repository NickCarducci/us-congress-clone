import importlib.util, pathlib, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("as_fono", here / "as_fono.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

# One item's fields as the Fono Senate site embeds them (field ids vary by page).
FIELDS = [
    ("Senate Resolution", []), ("Session 1", []), ("January 27, 2025", []),
    ("CONFIRMATION-DIRECTOR, DEPARTMENT OF PUBLIC WORKS.", []),
    ("This resolution confirms the Governor's appointment of Mr. Taeaotui P. Tilei.", []),
    ("Hon. Levu Sa losia Jr., District #7: Ituau 1.", []),
    ("1st Reading (Introduced): 01/27/2025, assigned to Sen. Levu. 2nd Reading Passed, 1/30/2025, Passed 12 Yes & 4 No (2 Absent).", []),
    ("S.R. No. 39-2", ["https://example.usrfiles.com/ugd/x.pdf"]),
    ("FONO Senate Progress Bar * { box-sizing: border-box; }", []),
]


class AsFono(unittest.TestCase):
    def test_an_item_becomes_an_open_states_bill(self):
        bill = module.measure(FIELDS, "39", "https://www.asfono.gov/391documents")
        self.assertEqual(bill["identifier"], "SR 39-2")
        self.assertEqual(bill["classification"], ["resolution"])
        self.assertEqual(bill["title"], "Confirmation-Director, Department of Public Works")
        self.assertEqual(bill["sponsorships"][0]["name"], "Hon. Levu Sa losia Jr.")
        self.assertEqual(bill["extras"]["sponsor_district"], "7")
        self.assertEqual([a["date"] for a in bill["actions"]], ["2025-01-27", "2025-01-27", "2025-01-30"])
        self.assertEqual(bill["versions"][0]["links"][0]["url"], "https://example.usrfiles.com/ugd/x.pdf")

    def test_numbers_however_the_site_punctuates_them(self):
        for written, number in [("S.C,R. No. 39-6", "SCR 39-6"), ("S.C.R No. 39-07", "SCR 39-7"),
                                ("S.B. No. 39-11", "SB 39-11"), ("S.J.R. No. 39-1", "SJR 39-1")]:
            bill = module.measure([(written, [])], "39", "u")
            self.assertEqual(bill["identifier"], number, written)

    def test_an_item_without_a_number_is_skipped(self):
        self.assertIsNone(module.measure([("Senate Bill", []), ("Session 1", [])], "39", "u"))


if __name__ == "__main__":
    unittest.main()
