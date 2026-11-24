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

    def test_party_regex_now_accepts_independent_democrats(self):
        import re
        pattern = r'(?P<title>(Rep\.|Sen\.|Del\.|Resident Commissioner|Rescom\.)) (?P<name>.*?) +\[(?P<party>[A-Z]{1,3})-(?P<state>[A-Z][A-Z])(-(?P<district>\d{1,2}|At Large|None))?\]$'
        self.assertEqual(re.match(pattern, 'Sen. Lieberman, Joseph I. [ID-CT]').group('party'), 'ID')
        self.assertEqual(re.match(pattern, 'Rep. Pelosi, Nancy [D-CA-8]').group('party'), 'D')


if __name__ == "__main__":
    unittest.main()
