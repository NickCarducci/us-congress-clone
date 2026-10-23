import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import types
import unittest

import archive_store
import archive_resume


class ArchiveTests(unittest.TestCase):
    def test_checkpoint_roundtrip_checksums_and_no_pdf_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, output, restored = base / 'source', base / 'output', base / 'restored'
            output.mkdir()
            bill = root / 'data/118/bills/hr/hr5536'
            bill.mkdir(parents=True)
            (bill / 'data.json').write_text('{"congress":118}')
            (bill / 'package.zip').write_bytes(b'PDF-containing source archive')
            chunks, count, _ = archive_store.pack(root, output, 'status-118-test', chunk_size=100)
            self.assertGreater(len(chunks), 1)
            self.assertEqual(count, 1)
            archive_store.unpack(chunks, output, restored)
            self.assertEqual((restored / bill.relative_to(root) / 'data.json').read_text(), '{"congress":118}')
            self.assertFalse(list(restored.rglob('*.zip')))
            (output / chunks[0]['name']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                archive_store.unpack(chunks, output, base / 'corrupt')

    def test_compact_export_keeps_browsing_metadata_and_text_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'
            bill = root / 'data/118/bills/hr/hr1'
            bill.mkdir(parents=True)
            (bill / 'data.json').write_text('{"congress":118,"number":1}')
            (bill / 'fdsys_billstatus.xml').write_text('<bill><actions>large data</actions><textVersions><item>text</item></textVersions></bill>')
            output = Path(temporary) / 'mirror'
            self.assertEqual(archive_store.export_metadata(root, output, 118), 1)
            self.assertEqual((output / bill.relative_to(root) / 'populist-text-versions.xml').read_text(), '<textVersions><item>text</item></textVersions>')
            self.assertFalse(list(output.rglob('fdsys_billstatus.xml')))

    def test_text_bundles_preserve_bill_and_print_version_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bill, version, value in [(5536, 'ih', 'Original'), (5536, 'eh', 'Amended'), (5600, 'ih', 'Different')]:
                folder = root / f'data/118/bills/hr/hr{bill}/text-versions/{version}'
                folder.mkdir(parents=True)
                (folder / 'document.txt').write_text(value)
            bundles = dict(archive_store.text_bundles(root, 118))
            self.assertEqual(bundles['text-118-hr-0055.json.gz']['bills']['5536'], {'eh':'Amended','ih':'Original'})
            self.assertEqual(bundles['text-118-hr-0056.json.gz']['bills']['5600'], {'ih':'Different'})

    def test_early_congress_text_metadata_is_browsable_without_fabricated_action_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'
            version = root / 'data/103/bills/sconres/sconres23/text-versions/es'
            version.mkdir(parents=True)
            (version / 'mods.xml').write_text('<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Conditional recess of Congress</title></titleInfo><originInfo><dateIssued>1993-04-07</dateIssued></originInfo></mods>')
            destination = Path(temporary) / 'mirror'
            self.assertEqual(archive_store.export_text_catalog(root, destination, 103), 1)
            bill = destination / 'data/103/bills/sconres/sconres23'
            record = json.loads((bill / 'data.json').read_text())
            self.assertEqual(record['official_title'], 'Conditional recess of Congress')
            self.assertEqual(record['actions'], [])
            self.assertNotIn('introduced_at', record)
            self.assertIn('BILLS-103sconres23es', (bill / 'populist-text-versions.xml').read_text())

    def test_resume_skips_unchanged_extracted_versions_and_refetches_changes(self):
        calls = []
        original = sys.modules.get('govinfo')
        module = types.SimpleNamespace(mirror_package=lambda *args: calls.append(args) or ['downloaded'])
        sys.modules['govinfo'] = module
        try:
            archive_resume.patch('govinfo')
            cache = {'118hr1ih':{'files':{'package':'date', 'text':'date', 'mods':'date'}}}
            self.assertEqual(module.mirror_package('BILLS', '118hr1ih', 'date', cache, {'extract':'mods,text'}), [])
            self.assertEqual(module.mirror_package('BILLS', '118hr1ih', 'new', cache, {'extract':'mods,text'}), ['downloaded'])
            self.assertEqual(len(calls), 1)
        finally:
            if original is None:
                del sys.modules['govinfo']
            else:
                sys.modules['govinfo'] = original

    def test_rejects_path_traversal_even_with_valid_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blob = io.BytesIO()
            with tarfile.open(fileobj=blob, mode='w:gz') as archive:
                member = tarfile.TarInfo('../outside')
                member.size = 3
                archive.addfile(member, io.BytesIO(b'bad'))
            data = blob.getvalue()
            (root / 'part').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                archive_store.unpack([{'name':'part','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}], root, root / 'restored')


if __name__ == '__main__':
    unittest.main()
