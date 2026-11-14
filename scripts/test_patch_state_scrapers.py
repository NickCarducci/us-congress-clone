import importlib.util, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location("patches", pathlib.Path(__file__).with_name("patch_state_scrapers.py"))
patches = importlib.util.module_from_spec(spec); spec.loader.exec_module(patches)


class PatchStateScrapers(unittest.TestCase):
    def tree(self):
        root = pathlib.Path(tempfile.mkdtemp())
        files = {}   # one file can carry several patches (South Carolina has two)
        for relative, old, _ in patches.PATCHES:
            files[relative] = files.get(relative, "before\n") + old + "between\n"
        for relative, text in files.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(text + "after\n")
        return root

    def test_patches_apply_once(self):
        root = self.tree()
        patches.main(root); patches.main(root)
        for relative, old, new in patches.PATCHES:
            text = (root / relative).read_text()
            self.assertEqual(text.count(new), 1, relative)

    def test_changed_upstream_code_is_left_alone(self):
        root = self.tree()
        (root / "scrapers/sc/bills.py").write_text("rewritten upstream\n")
        patches.main(root)
        self.assertEqual((root / "scrapers/sc/bills.py").read_text(), "rewritten upstream\n")

    def test_a_workaround_steps_aside_once_upstream_has_the_real_fix(self):
        root = self.tree()
        md = root / "scrapers/md/__init__.py"
        md.write_text(md.read_text() + '    {"_scraped_name": "2027 Regular Session", "identifier": "2027RS"},\n')
        patches.main(root)
        self.assertNotIn("patched in by us-congress-clone", md.read_text())


if __name__ == "__main__":
    unittest.main()
