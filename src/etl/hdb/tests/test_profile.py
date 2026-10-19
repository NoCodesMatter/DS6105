"""Regression tests for preserving a complete set of profiling evidence."""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
from core import REQUIRED, sha256, write_json

# Avoid colliding with Python's standard-library profile module.
spec = importlib.util.spec_from_file_location("hdb_profile", MODULE / "profile.py")
hdb_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hdb_profile)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "data/manifests/hdb_sources.json"
        self.manifest.parent.mkdir(parents=True)
        self.output = self.root / "evidence"
        self.output.mkdir()
        self.previous = {name: ("OLD " + name + "\r\n").encode()
                         for name in hdb_profile.EVIDENCE_FILES}
        for name, data in self.previous.items():
            (self.output / name).write_bytes(data)
        (self.output / "stage1_validation.json").write_text("UNRELATED", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def source(self, malformed=False):
        path = self.root / "source.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(REQUIRED)
            writer.writerow(("2015-01", "ANG MO KIO", "3 ROOM", "174", "ANG MO KIO AVE 4",
                             "07 TO 09", "60", "Improved", "1986", "255000"))
            if malformed:
                writer.writerow(("incomplete",))
        write_json(self.manifest, {"sources": [{
            "dataset_id": "d_" + "1" * 32, "label": "one", "path": path.name,
            "header": list(REQUIRED), "rows": 2 if malformed else 1, "sha256": sha256(path),
        }]})

    def run_profile(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return hdb_profile.profile(self.manifest, self.output, self.root)

    def assert_previous_preserved(self):
        for name, previous in self.previous.items():
            self.assertEqual((self.output / name).read_bytes(), previous, name)
        self.assertEqual((self.output / "stage1_validation.json").read_text(), "UNRELATED")

    def test_malformed_csv_leaves_previous_evidence_untouched(self):
        self.source(malformed=True)
        with self.assertRaisesRegex(ValueError, "Malformed CSV record 2"):
            self.run_profile()
        self.assert_previous_preserved()
        self.assertFalse(list(self.root.glob(".hdb-profile-*")))

    def test_report_generation_failure_leaves_previous_evidence_untouched(self):
        self.source()
        with patch.object(hdb_profile, "write_json", side_effect=OSError("fixture write failure")):
            with self.assertRaisesRegex(OSError, "fixture write failure"):
                self.run_profile()
        self.assert_previous_preserved()

    def test_failed_publish_rolls_back_already_replaced_file(self):
        self.source()
        original = Path.replace

        def fail_second_file(path, target):
            if path.parent.name == "generated" and path.name == "profile.md":
                raise OSError("fixture publish failure")
            return original(path, target)

        with patch.object(Path, "replace", fail_second_file):
            with self.assertRaisesRegex(OSError, "fixture publish failure"):
                self.run_profile()
        self.assert_previous_preserved()

    def test_success_updates_all_profile_files_and_preserves_other_evidence(self):
        self.source()
        report = self.run_profile()
        self.assertEqual(report["total_source_records"], 1)
        self.assertEqual(json.loads((self.output / "profile.json").read_text()), report)
        self.assertIn("| one | 2015-01 to 2015-01 | 1 |", (self.output / "profile.md").read_text())
        self.assertEqual(len((self.output / "source_issues.csv").read_text().splitlines()), 1)
        self.assertEqual((self.output / "stage1_validation.json").read_text(), "UNRELATED")

    def test_external_root_defaults_to_its_own_manifest_and_evidence(self):
        with patch.object(hdb_profile, "profile") as mocked:
            hdb_profile.main(["--root", str(self.root)])
        mocked.assert_called_once_with(self.manifest, self.root / "data/manifests/hdb_profile", self.root)


if __name__ == "__main__":
    unittest.main()
