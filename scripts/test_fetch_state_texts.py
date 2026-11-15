import importlib.util, json, os, pathlib, tempfile, unittest

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("fetch_state_texts", here / "fetch_state_texts.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def bill(identifier, date, url, media="text/html"):
    return {"identifier": identifier, "legislative_session": "222", "actions": [{"date": date}],
            "versions": [{"note": "Introduced", "date": date, "links": [{"url": url, "media_type": media}]}]}


class FetchStateTexts(unittest.TestCase):
    def test_latest_version_prefers_html(self):
        b = {"versions": [{"note": "I", "date": "2026-01-01", "links": [{"url": "old.pdf", "media_type": "application/pdf"}]},
                          {"note": "A", "date": "2026-03-01", "links": [{"url": "new.pdf", "media_type": "application/pdf"},
                                                                         {"url": "new.htm", "media_type": "text/html"}]}]}
        self.assertEqual(module.latest_version(b), ("new.htm", "A", "text/html"))

    def test_windows_1252_pages_decode(self):
        self.assertEqual(module.decode("Sponsor’s".encode("cp1252"), "text/html"), "Sponsor’s")
        self.assertEqual(module.decode("é".encode("utf-8"), "text/html; charset=utf-8"), "é")

    def test_fetches_newest_first_and_skips_what_it_has(self):
        with tempfile.TemporaryDirectory() as scrape, tempfile.TemporaryDirectory() as out:
            for i, (ident, date) in enumerate([("A 1", "2026-01-01"), ("A 2", "2026-11-01")]):
                json.dump(bill(ident, date, f"https://leg/{ident}.htm"), open(os.path.join(scrape, f"bill_{i}.json"), "w"))
            asked = []
            def fetch(url):
                asked.append(url)
                return b"<html><p>Be it enacted</p><script>x</script></html>", "text/html"
            module.main([scrape, out, "--rpm", "6000"], fetch=fetch, sleep=lambda s: None)
            self.assertEqual(asked, ["https://leg/A 2.htm", "https://leg/A 1.htm"], "newest activity first")
            index = json.load(open(os.path.join(out, "index.json")))
            text = open(os.path.join(out, index["222|A 2"]["file"])).read()
            self.assertEqual(text, "Be it enacted")
            asked.clear()
            module.main([scrape, out, "--rpm", "6000"], fetch=fetch, sleep=lambda s: None)
            self.assertEqual(asked, [], "unchanged versions aren't fetched again")


if __name__ == "__main__":
    unittest.main()
