import tempfile
import unittest
from pathlib import Path

import patch_scraper


class PatchScraperTests(unittest.TestCase):
    def test_patches_source_system_and_party_codes_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "congress/tasks/bill_info.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "            if item['sourceSystem'].get('code') == \"9\":\n"
                "    m = re.match(r'(?P<title>(Rep\\.|Sen\\.)) (?P<name>.*?) +\\[(?P<party>[DRIL])-(?P<state>[A-Z][A-Z])\\]$', x)\n")
            self.assertEqual(patch_scraper.patch(temporary), 2)
            text = source.read_text()
            self.assertIn("(item.get('sourceSystem') or {}).get('code')", text)
            self.assertIn("(?P<party>[A-Z]{1,3})", text)
            self.assertEqual(patch_scraper.patch(temporary), 2, "Running again is harmless")

    def test_house_meetings_post_over_https_without_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "congress/tasks/committee_meetings.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def fetch_house_committee_meetings(committees, options, opts, cmte):\n"
                "    committee_html = utils.download(\"http://docs.house.gov/Committee/Committees.aspx\", \"x\", opts)\n"
                "    html = utils.download(\n"
                "        \"http://docs.house.gov/Committee/RSS.ashx?Code=%s\" % cmte,\n"
                "        \"y\", opts)\n"
                "def extract_meeting_package(eventurl, event_id, options):\n"
                "    br = mechanize.Browser()\n"
                "    br.open(eventurl)\n"
                "    br.select_form(nr=0)\n"
                "    br.form.new_control(\"hidden\", \"__EVENTTARGET\", {})\n"
                "    br.form.new_control(\"hidden\", \"__EVENTARGUMENT\", {})\n")
            self.assertEqual(patch_scraper.patch(temporary), 5, "bill_info.py is missing here; the meeting fixes apply")
            text = source.read_text()
            self.assertIn('br.open(eventurl.replace("http://", "https://", 1))', text)
            self.assertNotIn("http://docs.house.gov", text, "every House address is https")
            self.assertIn('if not any(c.name == "__EVENTTARGET" for c in br.form.controls):', text)
            compile(text, "committee_meetings.py", "exec")

    def test_party_regex_now_accepts_independent_democrats(self):
        import re
        pattern = r'(?P<title>(Rep\.|Sen\.|Del\.|Resident Commissioner|Rescom\.)) (?P<name>.*?) +\[(?P<party>[A-Z]{1,3})-(?P<state>[A-Z][A-Z])(-(?P<district>\d{1,2}|At Large|None))?\]$'
        self.assertEqual(re.match(pattern, 'Sen. Lieberman, Joseph I. [ID-CT]').group('party'), 'ID')
        self.assertEqual(re.match(pattern, 'Rep. Pelosi, Nancy [D-CA-8]').group('party'), 'D')


if __name__ == "__main__":
    unittest.main()
