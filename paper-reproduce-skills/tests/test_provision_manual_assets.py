"""Unit tests for scripts/provision_manual_assets.py (stdlib unittest only)."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import provision_manual_assets as pma  # noqa: E402


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.registry = os.path.join(self.dir.name, "registry")
        self.repo = os.path.join(self.dir.name, "repo")
        os.makedirs(os.path.join(self.registry, "smpl"))
        os.makedirs(self.repo)
        with open(os.path.join(self.registry, "smpl", "SMPL_NEUTRAL.pkl"), "wb") as f:
            f.write(b"x" * 1024)
        with open(os.path.join(self.registry, "smpl", "EMPTY.pkl"), "wb"):
            pass
        self._old_cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self.dir.cleanup()

    def _place(self, src, dest):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pma.main(["place", "--root", self.registry,
                           "--src", src, "--dest", dest, "--asset", "smpl"])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_placed_and_gitignored(self):
        out = self._place("smpl/SMPL_NEUTRAL.pkl", "models/SMPL_NEUTRAL.pkl")
        self.assertEqual(out["status"], "placed")
        self.assertEqual(out["bytes"], 1024)
        self.assertTrue(out["gitignored"])
        self.assertTrue(os.path.isfile("models/SMPL_NEUTRAL.pkl"))
        with open(".gitignore") as f:
            self.assertIn("models/SMPL_NEUTRAL.pkl", f.read())

    def test_missing_in_registry(self):
        out = self._place("smpl/NOPE.pkl", "models/NOPE.pkl")
        self.assertEqual(out["status"], "missing_in_registry")
        self.assertFalse(os.path.exists("models/NOPE.pkl"))

    def test_placed_empty(self):
        out = self._place("smpl/EMPTY.pkl", "models/EMPTY.pkl")
        self.assertEqual(out["status"], "placed_empty")

    def test_src_traversal_rejected(self):
        secret = os.path.join(self.dir.name, "secret.txt")
        with open(secret, "w") as f:
            f.write("secret")
        out = self._place("../secret.txt", "models/out.txt")
        self.assertEqual(out["status"], "invalid_path")
        self.assertFalse(os.path.exists("models/out.txt"))

    def test_src_absolute_rejected(self):
        out = self._place(os.path.join(self.registry, "smpl", "SMPL_NEUTRAL.pkl"),
                          "models/out.pkl")
        self.assertEqual(out["status"], "invalid_path")

    def test_src_symlink_escape_rejected(self):
        secret = os.path.join(self.dir.name, "secret.txt")
        with open(secret, "w") as f:
            f.write("secret")
        os.symlink(secret, os.path.join(self.registry, "link.txt"))
        out = self._place("link.txt", "models/out.txt")
        self.assertEqual(out["status"], "invalid_path")

    def test_dest_escape_rejected(self):
        out = self._place("smpl/SMPL_NEUTRAL.pkl", "../outside.pkl")
        self.assertEqual(out["status"], "invalid_path")
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "outside.pkl")))

    def test_no_tmp_leftover(self):
        self._place("smpl/SMPL_NEUTRAL.pkl", "models/SMPL_NEUTRAL.pkl")
        leftovers = [p for p in os.listdir("models") if p.endswith(".tmp-provision")]
        self.assertEqual(leftovers, [])


class TestInventory(unittest.TestCase):
    def test_inventory_lists_missing_with_url(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            with open(manifest, "w") as f:
                json.dump({"assets": [
                    {"key": "smpl", "display_name": "SMPL",
                     "canonical_files": ["smpl/SMPL_NEUTRAL.pkl"],
                     "source_url": "https://smpl.is.tue.mpg.de/"}]}, f)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pma.main(["inventory", "--root", os.path.join(d, "none"),
                               "--manifest", manifest, "--lang", "en"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("smpl/SMPL_NEUTRAL.pkl", out)
            self.assertIn("https://smpl.is.tue.mpg.de/", out)


if __name__ == "__main__":
    unittest.main()
