"""Regression tests for data loss, source identity and historical format edges."""
from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import REQUIRED, normalize, remaining_lease, sha256, write_json
from pipeline import build
from verify import verify


def raw(**overrides):
    row = dict(zip(REQUIRED, ("2015-01", "ANG MO KIO", "3 ROOM", "174", "ANG MO KIO AVE 4",
                             "07 TO 09", "60", "Improved", "1986", "255000")))
    row.update(overrides)
    return row


class ParsingTests(unittest.TestCase):
    def test_lease_formats_and_precision(self):
        for value, expected in ((None, (840, "estimated_years", None)),
                                ("70", (840, "reported_years", None)),
                                ("61 years 04 months", (736, "reported_months", None)),
                                ("61 years", (732, "reported_months", None)),
                                ("0 years 01 month", (1, "reported_months", None))):
            with self.subTest(value=value):
                self.assertEqual(remaining_lease(value, 2015, 1986), expected)

    def test_bad_reported_lease_never_becomes_estimate(self):
        for value in ("", "N/A", "70.5", "NaN", "61 years 12 months", "100", "-1", "70 years junk"):
            with self.subTest(value=value):
                result = remaining_lease(value, 2015, 1986)
                self.assertEqual(result[:2], (None, "unknown"))
                self.assertIsNotNone(result[2])

    def test_future_lease_retains_transaction_as_unknown(self):
        row, _, warnings = normalize(raw(month="1990-01", lease_commence_date="2013"))
        self.assertIsNone(row["remaining_lease_months"])
        self.assertEqual(row["lease_basis"], "unknown")
        self.assertEqual(set(warnings), {"estimated_lease_out_of_range", "transaction_before_lease_commencement_year"})

    def test_exact_profile_normalization_preserves_bin_and_address(self):
        row, changes, _ = normalize(raw(block=" 10a ", street_name=" Example\u00a0 ST ",
                                       storey_range="06 TO 10", flat_type="MULTI-GENERATION", floor_area_sqm="90.5"))
        self.assertEqual((row["block"], row["street_name"]), ("10A", "EXAMPLE ST"))
        self.assertEqual((row["storey_lower"], row["storey_upper"]), (6, 10))
        self.assertEqual(row["flat_type"], "MULTI GENERATION")
        self.assertEqual(row["floor_area_sqm"], "90.50")
        self.assertEqual(row["sale_month"], "2015-01-01")
        self.assertEqual(changes["mapped_MULTI-GENERATION"], 1)

    def test_invalid_mandatory_values_fail(self):
        cases = [("floor_area_sqm", v) for v in ("0", "-1", "90.001", "NaN", "Infinity", "1000000")]
        cases += [("resale_price", v) for v in ("0", "1.001", "1000000000000")]
        cases += [("storey_range", v) for v in ("09 TO 07", "00 TO 03", "1", "01 TO 32768")]
        cases += [("month", "2015-13"), ("lease_commence_date", "0"), ("town", ""), ("flat_type", "OTHER"),
                  ("street_name", "ANG MO KIO\x00 AVE 4")]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                normalize(raw(**{field: value}))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "sources.json"
        self.sources = []

    def tearDown(self):
        self.temp.cleanup()

    def source(self, rows, label="one"):
        dataset = "d_" + str(len(self.sources) + 1) * 32
        path = self.root / f"{label}.csv"
        header = list(rows[0])
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        self.sources.append({"dataset_id": dataset, "label": label, "path": path.name,
                             "sha256": sha256(path), "rows": len(rows), "header": header,
                             "snapshot_utc": "2026-10-18T00:00:00+00:00",
                             "source_url": f"https://data.gov.sg/datasets/{dataset}/view"})
        write_json(self.manifest, {"sources": self.sources})
        return path

    def run_build(self, selectors=None, dirname="out"):
        with contextlib.redirect_stdout(io.StringIO()):
            result = build(self.manifest, selectors or [s["label"] for s in self.sources],
                           self.root / dirname, dirname, self.root)
        return result

    def rows(self, table, dirname="out"):
        with (self.root / dirname / f"{table}.csv").open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def test_identical_transactions_preserved_and_multiline_ordinals(self):
        self.source([raw(flat_model="Improved\nModel"), raw(flat_model="Improved\nModel")])
        result = self.run_build()
        transactions = self.rows("resale_transaction")
        self.assertEqual(result["tables"]["hdb_flat"]["rows"], 1)
        self.assertEqual([t["source_row"] for t in transactions], ["1", "2"])
        self.assertNotEqual(transactions[0]["transaction_id"], transactions[1]["transaction_id"])
        self.assertEqual(verify(self.root / "out", self.manifest, self.root)["source_records_reconciled"], 2)

    def test_repeated_and_cumulative_input_order_is_deterministic(self):
        self.source([raw(remaining_lease="70")], "one")
        self.source([raw(remaining_lease="61 years 04 months", month="2017-01")], "two")
        one = self.run_build(["one", "two"])
        two = self.run_build(["two", "one"], "repeat")
        self.assertEqual(one["tables"], two["tables"])
        self.assertEqual(one["tables"]["resale_transaction"]["rows"], 2)
        self.assertEqual(one["tables"]["hdb_building"]["rows"], 1)
        self.assertEqual(verify(self.root / "repeat", self.manifest, self.root)["status"], "passed")

    def test_unknown_lease_is_empty_unquoted_and_not_a_dropped_sale(self):
        self.source([raw(remaining_lease="N/A")])
        result = self.run_build()
        text = (self.root / "out/resale_transaction.csv").read_text(encoding="utf-8")
        self.assertIn(",,unknown,", text)
        self.assertEqual(result["accepted_records"], 1)
        self.assertEqual(result["warnings"]["invalid_reported_lease_syntax"], 1)
        self.assertEqual(verify(self.root / "out", self.manifest, self.root)["status"], "passed")

    def test_conflicting_town_blocks_publication(self):
        self.source([raw()], "one")
        self.source([raw(town="BEDOK")], "two")
        with self.assertRaisesRegex(ValueError, "Stage rejected"):
            self.run_build()
        self.assertFalse((self.root / "out").exists())
        failure = json.loads((self.root / "out.failed/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["status"], "failed")
        self.assertIn("multiple towns", (self.root / "out.failed/diagnostics.csv").read_text(encoding="utf-8"))

    def test_invalid_mandatory_record_cannot_publish_partial_stage(self):
        self.source([raw(), raw(resale_price="0")])
        with self.assertRaisesRegex(ValueError, "Stage rejected"):
            self.run_build()
        self.assertFalse((self.root / "out").exists())
        self.assertTrue((self.root / "out.failed/diagnostics.csv").exists())

    def test_building_lease_variants_are_reported_not_merged(self):
        self.source([raw(lease_commence_date="1981"), raw(lease_commence_date="1982")])
        result = self.run_build()
        self.assertEqual(result["tables"]["hdb_flat"]["rows"], 2)
        self.assertEqual(result["buildings_with_multiple_lease_years"][0]["lease_commence_years"], [1981, 1982])

    def test_changed_snapshot_rejected(self):
        path = self.source([raw()])
        with path.open("a", encoding="utf-8") as f:
            f.write("\n")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            self.run_build()

    def test_duplicate_dataset_selection_rejected(self):
        self.source([raw()])
        with self.assertRaisesRegex(ValueError, "included twice"):
            self.run_build(["one", "one"])

    def test_existing_stage_preserved(self):
        self.source([raw()])
        self.run_build()
        before = sha256(self.root / "out/resale_transaction.csv")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            self.run_build()
        self.assertEqual(before, sha256(self.root / "out/resale_transaction.csv"))

    def test_tampered_output_rejected(self):
        self.source([raw()])
        self.run_build()
        path = self.root / "out/town.csv"
        path.write_text("town_name\nCHANGED\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Output hash mismatch"):
            verify(self.root / "out", self.manifest, self.root)

    def test_nul_text_blocks_publication(self):
        self.source([raw(street_name="ANG MO KIO\x00 AVE 4")])
        with self.assertRaisesRegex(ValueError, "Stage rejected"):
            self.run_build()
        self.assertFalse((self.root / "out").exists())
        self.assertIn("NUL character", (self.root / "out.failed/diagnostics.csv").read_text(encoding="utf-8"))

    def test_verifier_rejects_nul_even_when_csv_hash_matches(self):
        self.source([raw()])
        self.run_build()
        path = self.root / "out/town.csv"
        path.write_bytes(path.read_bytes().replace(b"ANG MO KIO", b"ANG MO KIO\x00"))
        manifest_path = self.root / "out/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tables"]["town"]["sha256"] = sha256(path)
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "NUL character"):
            verify(self.root / "out", self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
