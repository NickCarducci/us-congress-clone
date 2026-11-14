import importlib.util, json, os, pathlib, tempfile, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("check_scrape", here / "check_scrape.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

GOOD = {"identifier": "HB 1", "title": "A bill", "legislative_session": "2026", "actions": []}


def write(directory, name, value):
    path = os.path.join(directory, name)
    with open(path, "w") as handle:
        handle.write(value if isinstance(value, str) else json.dumps(value))
    return path


class CheckScrape(unittest.TestCase):
    def test_proper_bills_pass(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(10):
                write(d, f"bill_{i}.json", GOOD)
            self.assertEqual(module.check(d, "2026"), {"bills": 10, "invalid": 0, "examples": [], "proper": True})

    def test_a_few_odd_bills_among_many_still_pass(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(200):
                write(d, f"bill_{i}.json", GOOD)
            for i in range(3):
                write(d, f"bill_bad{i}.json", {**GOOD, "title": ""})
            self.assertTrue(module.check(d, "2026")["proper"])

    def test_the_wrong_session_or_broken_files_fail(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                write(d, f"bill_{i}.json", {**GOOD, "legislative_session": "2025"})
            result = module.check(d, "2026")
            self.assertFalse(result["proper"])
            self.assertIn("session '2025', expected '2026'", result["examples"][0])
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                old = write(d, f"bill_{i}.json", "{not json")
                os.utime(old, (0, 0))
            self.assertFalse(module.check(d)["proper"])

    def test_a_sample_reads_only_the_newest(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                old = write(d, f"bill_old{i}.json", {**GOOD, "legislative_session": "2025"})
                os.utime(old, (1, 1))
            for i in range(3):
                write(d, f"bill_{i}.json", GOOD)
            self.assertEqual(module.check(d, "2026", sample=3)["bills"], 3)
            self.assertTrue(module.check(d, "2026", sample=3)["proper"])

    def test_a_file_being_written_is_skipped_and_none_yet_is_proper(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(module.check(d)["bills"], 0)
            self.assertTrue(module.check(d)["proper"])
            write(d, "bill_half.json", '{"identifier": "HB')
            self.assertEqual(module.check(d)["bills"], 0)


if __name__ == "__main__":
    unittest.main()
