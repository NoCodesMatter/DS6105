"""Check that source provenance survives Git newline conversion, not code edits."""
import contextlib
import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
import pipeline
import verify


class ProvenanceTests(unittest.TestCase):
    def test_source_newlines_only_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            lf, crlf, edited = (Path(directory) / x for x in ("lf.py", "crlf.py", "edited.py"))
            lf.write_bytes(b"x = 1\ny = 2\n")
            crlf.write_bytes(b"x = 1\r\ny = 2\r\n")
            edited.write_bytes(b"x = 2\ny = 2\n")
            self.assertEqual(core.code_sha256(lf), core.code_sha256(crlf))
            self.assertNotEqual(core.sha256(lf), core.sha256(crlf))
            self.assertNotEqual(core.code_sha256(lf), core.code_sha256(edited))

    def test_saved_stage_verifies_after_other_platform_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "source.csv"
            with raw_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(core.REQUIRED)
                writer.writerow(("2015-01", "ANG MO KIO", "3 ROOM", "174", "ANG MO KIO AVE 4",
                                 "07 TO 09", "60", "Improved", "1986", "255000"))
            source = {"dataset_id": "d_" + "1" * 32, "label": "fixture", "path": "source.csv",
                      "sha256": core.sha256(raw_path), "header": list(core.REQUIRED), "rows": 1,
                      "source_url": "https://data.gov.sg/collections/189/view", "snapshot_utc": "2026-10-18T00:00:00Z"}
            manifest = root / "sources.json"
            core.write_json(manifest, {"sources": [source]})
            with contextlib.redirect_stdout(io.StringIO()):
                result = pipeline.build(manifest, ["fixture"], root / "stage", "fixture", root)
            checkout = root / "different_checkout"
            for relative in result["code_sha256"]:
                destination = checkout / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                contents = (core.ROOT / relative).read_text(encoding="utf-8")
                destination.write_bytes(contents.replace("\n", "\r\n").encode("utf-8"))
            with patch.object(verify, "ROOT", checkout):
                self.assertEqual(verify.verify(root / "stage", manifest, root)["status"], "passed")
                with (checkout / "src/etl/hdb/core.py").open("a", encoding="utf-8") as f:
                    f.write("\n# Actual source change\n")
                with self.assertRaisesRegex(ValueError, "Build code changed"):
                    verify.verify(root / "stage", manifest, root)


if __name__ == "__main__":
    unittest.main()
