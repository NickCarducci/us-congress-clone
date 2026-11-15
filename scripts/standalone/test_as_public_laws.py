import importlib.util, pathlib, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("as_public_laws", here / "as_public_laws.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class AsPublicLaws(unittest.TestCase):
    def test_rows_however_each_collection_names_its_fields(self):
        law = module.law_from_row({"publicLawNo": "P.L. 38-01", "session": "1st Regular", "senateHouseBillNo": "S.B. 38-1",
            "aSCA": 17.0, "dateApproved": "January 27, 2023", "summary": "An Act appropriating",
            "document": "wix:document://v1/ugd/4c56eb_f68a6f.pdf/Copy%20of%20PL.pdf"}, "src")
        self.assertEqual((law["publicLaw"], law["bill"], law["asca"], law["approved"]), ("P.L. 38-01", "SB 38-1", "Title 17", "2023-01-27"))
        self.assertEqual(law["pdf"], "https://www.osas.as/_files/ugd/4c56eb_f68a6f.pdf")
        older = module.law_from_row({"plNo": "P.L. 20-88", "senateOrHouseBillNo": "S.B. 20-107", "dateApproved": "November, 1988"}, "src")
        self.assertEqual((older["publicLaw"], older["bill"], older["approved"]), ("P.L. 20-88", "SB 20-107", "1988-11"))
        oldest = module.law_from_row({"publicLawNo19th": "P.L. 19-26", "senateHouseBillNo": "H.B. 148", "dateApproved": "September 27th, 1985"}, "src")
        self.assertEqual((oldest["bill"], oldest["approved"]), ("HB 148", "1985-09-27"))
        self.assertIsNone(module.law_from_row({"summary": "no number"}, "src"))

    def test_bill_numbers(self):
        self.assertEqual(module.bill_number("H.B. 39-8"), "HB 39-8")
        self.assertEqual(module.bill_number("S.C.R. No. 38-2"), "SCR 38-2")
        self.assertIsNone(module.bill_number(""))


if __name__ == "__main__":
    unittest.main()
