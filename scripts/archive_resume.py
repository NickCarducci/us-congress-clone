"""Use extracted, checksummed checkpoints without retaining GovInfo's PDF-bearing ZIPs."""
import sys


def patch(task_name):
    if task_name != 'govinfo':
        return
    module = sys.modules[task_name]
    original = module.mirror_package

    def mirror_package(collection, package_name, lastmod, cache, options):
        formats = set(options.get('extract', '').split(','))
        saved = cache.get(package_name, {}).get('files', {})
        if saved.get('package') == lastmod and formats and all(saved.get(item) == lastmod for item in formats):
            return []
        return original(collection, package_name, lastmod, cache, options)

    module.mirror_package = mirror_package
