import gzip, importlib.util, io, json, pathlib, tempfile, unittest, zipfile

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("legiscan_datasets", here / "legiscan_datasets.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

# Trimmed from the getBill example in LegiScan's API manual (v1.91).
BILL = {"bill_id": 1167968, "state": "MD", "bill_number": "SB181", "body": "S",
        "title": "Education - Child Care Subsidies - Mandatory Funding Level", "description": "Altering certain classes",
        "url": "https://legiscan.com/MD/bill/SB181/2019",
        "state_link": "http://mgaleg.maryland.gov/mgawebsite/Legislation/Details/SB0181?ys=2019rs",
        "history": [{"date": "2019-01-23", "action": "First Reading Budget and Taxation", "chamber": "S"},
                    {"date": "2019-05-25", "action": "Enacted - Chapter 596", "chamber": "S"}],
        "sponsors": [{"name": "Nancy King", "sponsor_type_id": 1}, {"name": "Other", "sponsor_type_id": 2}],
        "subjects": [{"subject_id": 3309, "subject_name": "Education"}]}


class LegiScanDatasets(unittest.TestCase):
    def test_a_bill_reads_like_open_states(self):
        bill = module.to_open_states(BILL, "2019 Regular Session")
        self.assertEqual(bill["identifier"], "SB181")
        self.assertEqual(bill["chamber"], "upper")
        self.assertEqual(bill["legislative_session"], "2019 Regular Session")
        self.assertEqual([a["description"] for a in bill["actions"]], ["First Reading Budget and Taxation", "Enacted - Chapter 596"])
        self.assertEqual(bill["sponsors"], [{"name": "Nancy King", "primary": True}, {"name": "Other", "primary": False}])
        self.assertEqual(bill["sources"][0]["url"], BILL["state_link"], "the legislature's own page first")
        self.assertEqual(bill["subject"], ["Education"])

    def test_state_ids_follow_legiscan(self):
        self.assertEqual(module.state_of({"state_id": 5}), "ca")
        self.assertEqual(module.state_of({"state_id": 20}), "md")
        self.assertEqual(module.state_of({"state_id": 51}), "dc")
        self.assertIsNone(module.state_of({"state_id": 52}), "Congress is not a state")

    def test_a_zip_is_read_and_written_repeatably(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("MD/2019-2019_Regular_Session/bill/SB181.json", json.dumps({"bill": BILL}))
            archive.writestr("MD/2019-2019_Regular_Session/people/1.json", "{}")
        state, bills = module.bills_from_zip(buffer.getvalue())
        self.assertEqual((state, len(bills)), ("md", 1))
        with tempfile.TemporaryDirectory() as out:
            dataset = {"session_id": 1636, "session_name": "2019 Regular Session", "dataset_hash": "x"}
            module.write_session(out, "md", dataset, bills)
            path = pathlib.Path(out, "md", "md_ls1636.json.gz")
            first = path.read_bytes()
            module.write_session(out, "md", dataset, bills)
            self.assertEqual(path.read_bytes(), first, "unchanged sessions sync as unchanged")
            payload = json.loads(gzip.decompress(first))
            self.assertEqual(payload["legiscan"]["session_id"], 1636)
            self.assertEqual(payload["bills"][0]["identifier"], "SB181")


if __name__ == "__main__":
    unittest.main()
