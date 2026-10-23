"""Checkpoint public legislative datasets in GitHub Releases, outside Actions cache."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

SCHEMA = 1
CHUNK_SIZE = 1024 ** 3


def gh(*args, **kwargs):
    return subprocess.check_output(['gh', *args], text=True, **kwargs)


def manifest_name(kind):
    return f'{kind}-manifest.json'


def read_manifest(repo, tag, kind):
    result = subprocess.run(['gh', 'release', 'view', tag, '--repo', repo, '--json', 'assets'], capture_output=True, text=True)
    if result.returncode:
        if 'not found' in result.stderr.lower():
            return None
        raise RuntimeError(result.stderr)
    if not any(asset['name'] == manifest_name(kind) for asset in json.loads(result.stdout)['assets']):
        return None
    with tempfile.TemporaryDirectory() as temporary:
        gh('release', 'download', tag, '--repo', repo, '--pattern', manifest_name(kind), '--dir', temporary)
        return json.loads((Path(temporary) / manifest_name(kind)).read_text())


def validate_manifest(value, kind, congress):
    if value.get('schema') != SCHEMA or value.get('kind') != kind or value.get('congress') != congress:
        raise ValueError('Archive identity mismatch')
    if not value.get('chunks') or len(value['chunks']) > 100:
        raise ValueError('Invalid archive chunks')
    for chunk in value['chunks']:
        if Path(chunk['name']).name != chunk['name'] or not chunk['name'].startswith(f'{kind}-{congress}-'):
            raise ValueError('Invalid chunk name')
        if len(chunk['sha256']) != 64 or not 0 < chunk['bytes'] <= CHUNK_SIZE:
            raise ValueError('Invalid chunk digest or size')


def selected_files(root):
    for folder in ['data', 'cache']:
        for path in sorted((root / folder).rglob('*')):
            if path.is_file() and not path.is_symlink() and path.name not in ['package.zip', 'document.html']:
                yield path


class ChunkWriter(io.RawIOBase):
    def __init__(self, directory, prefix, limit=CHUNK_SIZE):
        self.directory, self.prefix, self.limit = directory, prefix, limit
        self.output = None
        self.chunks = []
        self.size = 0
        self.digest = None

    def writable(self):
        return True

    def finish_chunk(self):
        if self.output:
            self.output.close()
            self.chunks.append({'name': Path(self.output.name).name, 'bytes': self.size, 'sha256': self.digest.hexdigest()})
            self.output = None

    def write(self, value):
        total = len(value)
        while value:
            if self.output is None:
                self.output = (self.directory / f'{self.prefix}.part{len(self.chunks):03}').open('wb')
                self.size, self.digest = 0, hashlib.sha256()
            part = value[:self.limit - self.size]
            self.output.write(part)
            self.digest.update(part)
            self.size += len(part)
            value = value[len(part):]
            if self.size == self.limit:
                self.finish_chunk()
        return total


def pack(root, output, prefix, chunk_size=CHUNK_SIZE):
    writer = ChunkWriter(output, prefix, chunk_size)
    count, size = 0, 0
    with tarfile.open(fileobj=writer, mode='w|gz') as archive:
        for path in selected_files(root):
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
            count += 1
            size += path.stat().st_size
    writer.finish_chunk()
    return writer.chunks, count, size


def unpack(chunks, directory, root):
    with tempfile.TemporaryFile() as assembled:
        for chunk in chunks:
            path = directory / chunk['name']
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as source:
                while data := source.read(1024 * 1024):
                    digest.update(data)
                    size += len(data)
                    assembled.write(data)
            if size != chunk['bytes'] or digest.hexdigest() != chunk['sha256']:
                raise ValueError('Archive checksum mismatch')
        assembled.seek(0)
        with tarfile.open(fileobj=assembled, mode='r:gz') as archive:
            for member in archive:
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or path.parts[0] not in ['data', 'cache'] or not member.isfile():
                    raise ValueError('Unsafe archive member')
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open('wb') as target:
                    shutil.copyfileobj(source, target)


def export_metadata(root, destination, congress):
    import re
    count = 0
    for source in (root / 'data' / str(congress) / 'bills').glob('*/*/data.json'):
        value = json.loads(source.read_text())
        if int(value['congress']) != congress:
            raise ValueError('Bill Congress mismatch')
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        xml = source.with_name('fdsys_billstatus.xml')
        if xml.exists():
            match = re.search(r'<textVersions>[\s\S]*?</textVersions>', xml.read_text())
            target.with_name('populist-text-versions.xml').write_text(match.group(0) if match else '<textVersions/>')
        count += 1
    if count == 0:
        raise ValueError('No parsed bills to export')
    return count


def export_text_catalog(root, destination, congress):
    import xml.etree.ElementTree as ET
    count = 0
    namespace = {'mods': 'http://www.loc.gov/mods/v3'}
    for bill in (root / 'data' / str(congress) / 'bills').glob('*/*'):
        if not bill.is_dir():
            continue
        bill_type = bill.parent.name
        number = int(bill.name[len(bill_type):])
        versions = []
        for mods in bill.glob('text-versions/*/mods.xml'):
            document = ET.parse(mods)
            title = document.findtext('.//mods:titleInfo/mods:title', namespaces=namespace)
            issued = document.findtext('.//mods:dateIssued', namespaces=namespace)
            if title:
                versions.append((issued or '', mods.parent.name, title))
        if not versions:
            continue
        versions.sort(reverse=True)
        output = destination / bill.relative_to(root)
        output.mkdir(parents=True, exist_ok=True)
        # Print dates are not introduction/action dates; leave those fields unknown.
        record = {'congress': congress, 'bill_type': bill_type, 'number': number,
                  'official_title': versions[0][2], 'actions': [], 'committees': [],
                  'archive_source': 'govinfo-mods'}
        (output / 'data.json').write_text(json.dumps(record))
        element = ET.Element('textVersions')
        for date, version, _ in versions:
            item = ET.SubElement(element, 'item')
            ET.SubElement(item, 'type').text = version
            ET.SubElement(item, 'date').text = date
            formats = ET.SubElement(ET.SubElement(item, 'formats'), 'item')
            package = f'BILLS-{congress}{bill_type}{number}{version}'
            ET.SubElement(formats, 'url').text = f'https://www.govinfo.gov/content/pkg/{package}/xml/{package}.xml'
        (output / 'populist-text-versions.xml').write_text(ET.tostring(element, encoding='unicode'))
        count += 1
    if count == 0:
        raise ValueError('No MODS bill metadata to export')
    return count


def text_bundles(root, congress):
    from collections import defaultdict
    grouped = defaultdict(dict)
    for text in (root / 'data' / str(congress) / 'bills').glob('*/*/text-versions/*/document.txt'):
        bill_type = text.parents[3].name
        bill_number = int(text.parents[2].name[len(bill_type):])
        bucket = bill_number // 100
        grouped[(bill_type, bucket)].setdefault(str(bill_number), {})[text.parent.name] = text.read_text()
    for (bill_type, bucket), bills in sorted(grouped.items()):
        yield f'text-{congress}-{bill_type}-{bucket:04}.json.gz', {
            'schema': 1, 'congress': congress, 'type': bill_type, 'bucket': bucket, 'bills': bills}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['inspect', 'restore', 'publish', 'export', 'bundles', 'finish'])
    parser.add_argument('--kind', choices=['status', 'text'], required=True)
    parser.add_argument('--congress', type=int, required=True)
    parser.add_argument('--root', type=Path, default=Path('bill-scraper'))
    parser.add_argument('--output', type=Path, default=Path('compact-mirror'))
    parser.add_argument('--complete', choices=['true', 'false'], default='false')
    parser.add_argument('--refresh', choices=['true', 'false'], default='false')
    args = parser.parse_args()
    repo = os.environ['GITHUB_REPOSITORY']
    tag = f'legislation-{args.congress}'
    if args.operation == 'export':
        exporter = export_metadata if args.kind == 'status' else export_text_catalog
        print(f'Exported {exporter(args.root, args.output, args.congress)} compact bill records')
        return
    if args.operation == 'bundles':
        import gzip
        with tempfile.TemporaryDirectory() as temporary:
            for name, bundle in text_bundles(args.root, args.congress):
                content = json.dumps(bundle, ensure_ascii=False).encode()
                if len(content) > 64 * 1024 * 1024:
                    raise ValueError(f'Text lookup bundle exceeds reader limit: {name}')
                path = Path(temporary) / name
                encoded = gzip.compress(content)
                if len(encoded) > 32 * 1024 * 1024:
                    raise ValueError(f'Compressed text bundle exceeds reader limit: {name}')
                path.write_bytes(encoded)
                gh('release', 'upload', tag, str(path), '--repo', repo, '--clobber')
        return
    previous = read_manifest(repo, tag, args.kind)
    if previous:
        validate_manifest(previous, args.kind, args.congress)
    if args.operation == 'finish':
        if previous is None:
            raise ValueError('No published checkpoint to finalize')
        previous['complete'] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / manifest_name(args.kind)
            path.write_text(json.dumps(previous, indent=2) + '\n')
            gh('release', 'upload', tag, str(path), '--repo', repo, '--clobber')
        return
    if args.operation == 'inspect':
        skip = bool(previous and previous.get('complete') and args.refresh != 'true')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'skip={str(skip).lower()}\n')
        return
    if args.operation == 'restore':
        if previous:
            with tempfile.TemporaryDirectory() as temporary:
                for chunk in previous['chunks']:
                    gh('release', 'download', tag, '--repo', repo, '--pattern', chunk['name'], '--dir', temporary)
                unpack(previous['chunks'], Path(temporary), args.root)
        return
    # Each snapshot uses immutable asset names; publish its manifest only after all parts exist.
    result = subprocess.run(['gh', 'release', 'view', tag, '--repo', repo], capture_output=True)
    if result.returncode:
        created = subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--title', f'Congress {args.congress} public legislation', '--notes', 'Public GovInfo source data, extraction checkpoints and SHA-256 manifests. No PDFs are retained.'], capture_output=True)
        if created.returncode:
            gh('release', 'view', tag, '--repo', repo)
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        prefix = f'{args.kind}-{args.congress}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
        chunks, files, size = pack(args.root, output, prefix)
        for chunk in chunks:
            gh('release', 'upload', tag, str(output / chunk['name']), '--repo', repo)
        manifest = {'schema': SCHEMA, 'kind': args.kind, 'congress': args.congress, 'complete': args.complete == 'true', 'files': files, 'uncompressedBytes': size, 'chunks': chunks, 'source': 'https://www.govinfo.gov/', 'run': os.environ['GITHUB_RUN_ID']}
        path = output / manifest_name(args.kind)
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        gh('release', 'upload', tag, str(path), '--repo', repo, '--clobber')
        print(json.dumps({key:manifest[key] for key in ['kind', 'congress', 'complete', 'files', 'uncompressedBytes']}))


if __name__ == '__main__':
    main()
