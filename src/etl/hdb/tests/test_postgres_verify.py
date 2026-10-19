"""Unit regressions for safe database creation and actual-import verification plumbing.

Real PostgreSQL runs are separate evidence; these tests need no server or password.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import postgres_verify as pg


class PostgresVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def csv(self, name, rows, ending="\n"):
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator=ending).writerows(rows)
        return path

    def compare(self, expected, actual):
        return pg.compare_csv(expected, actual, self.root / "index.sqlite")

    def test_every_value_compared_independent_of_order_and_line_endings(self):
        expected = self.csv("expected.csv", [("id", "value", "optional"),
                             ("b", "123.40", ""), ("a", "中,文", "quoted\"text")])
        actual = self.csv("actual.csv", [("id", "value", "optional"),
                           ("a", "中,文", "quoted\"text"), ("b", "123.40", "")], "\r\n")
        result = self.compare(expected, actual)
        self.assertEqual(result["rows_compared"], 2)
        self.assertEqual(result["columns_compared"], 3)

    def test_roundtrip_detects_numeric_rounding(self):
        expected = self.csv("expected.csv", [("id", "value"), ("a", "123.40")])
        actual = self.csv("actual.csv", [("id", "value"), ("a", "123.41")])
        with self.assertRaisesRegex(ValueError, "changed values"):
            self.compare(expected, actual)

    def test_roundtrip_detects_missing_rows(self):
        expected = self.csv("expected.csv", [("id", "value"), ("a", "123.40")])
        actual = self.csv("actual.csv", [("id", "value")])
        with self.assertRaisesRegex(ValueError, "missing"):
            self.compare(expected, actual)

    def test_roundtrip_detects_duplicate_export_rows(self):
        expected = self.csv("expected.csv", [("id", "value"), ("a", "123.40")])
        actual = self.csv("actual.csv", [("id", "value"), ("a", "123.40"), ("a", "123.40")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.compare(expected, actual)

    def test_database_names_cannot_be_connection_strings_or_sql(self):
        self.assertEqual(pg.identifier("hdb_20261018"), '"hdb_20261018"')
        for name in ("postgresql://user:secret@host/db", "x;DROP DATABASE y", "a\nb", "a" * 64, ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pg.identifier(name)

    def test_import_uses_single_transaction_explicit_columns_and_safe_paths(self):
        script = pg.import_script(self.root / "O'Brien folder")
        self.assertTrue(script.startswith("BEGIN;\n"))
        self.assertTrue(script.endswith("COMMIT;\n"))
        positions = []
        for table in pg.HDB_TABLES:
            columns = ", ".join(pg.contract.CSV_COLUMNS[table])
            positions.append(script.index(f"\\copy housing.{table} ({columns})"))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(script.count("NULL ''"), 4)
        self.assertIn("O''Brien folder", script)
        self.assertNotIn("DROP", script)
        with self.assertRaises(ValueError):
            pg.import_script(self.root / "line\nbreak")

    def test_psql_noninteractive_settings_and_password_stays_out_of_command(self):
        captured = {}

        def process(args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs["env"]
            kwargs["stdout"].write(b"passed\n")
            return subprocess.CompletedProcess(args, 0, stderr=b"")

        with patch.dict(pg.os.environ, {"PGPASSWORD": "test-secret"}), patch.object(pg.subprocess, "run", process):
            result = pg.Psql("psql", "127.0.0.1", 55432, "test_user").execute("new_db", "SELECT 1;")
        self.assertEqual(result, "passed")
        self.assertNotIn("test-secret", " ".join(captured["args"]))
        self.assertEqual(captured["env"]["PGPASSWORD"], "test-secret")
        self.assertIn("--no-password", captured["args"])
        self.assertIn("-X", captured["args"])
        self.assertIn("ON_ERROR_STOP=1", captured["args"])

    def test_psql_failure_excludes_raw_error_details(self):
        result = subprocess.CompletedProcess([], 3, stderr=b'ERROR:  23505: secret-text\n')
        with patch.object(pg.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "23505") as caught:
                pg.Psql("psql", "127.0.0.1", 55432, "test_user").execute("new_db", "SELECT 1;")
        self.assertNotIn("secret-text", str(caught.exception))

    def test_rollback_probe_uses_real_import_path_and_checks_all_tables(self):
        row = ("id", "flat", "2015-01-01", "100.00", "840", "reported_years", "dataset", "1")
        self.csv("resale_transaction.csv", [pg.contract.CSV_COLUMNS["resale_transaction"], row])

        class FakePsql:
            def execute(inner, database, sql, expected_failure):
                self.assertEqual(expected_failure, ("23514", "transaction_positive_price"))
                self.assertEqual(sql.count("\\copy housing."), 4)
                self.assertLess(sql.index("housing.hdb_flat"), sql.index("housing.resale_transaction"))
                with (self.root / "rejected_transactions.csv").open(encoding="utf-8", newline="") as stream:
                    self.assertEqual(next(csv.DictReader(stream))["resale_price"], "0.00")
                return {"sqlstate": "23514"}

            def json(inner, database, sql):
                return {table: 0 for table in pg.HDB_TABLES}

        result = pg.rollback_probe(FakePsql(), "new_db", self.root, self.root)
        self.assertEqual(result["status"], "passed")
        with patch.object(pg, "table_counts", return_value={"town": 1}):
            with self.assertRaisesRegex(ValueError, "partially imported"):
                pg.rollback_probe(FakePsql(), "new_db", self.root, self.root)

    def test_constraint_probes_are_rollback_only_and_assert_sqlstate(self):
        statements = []

        class FakePsql:
            def execute(inner, database, sql):
                statements.append(sql)
                return "passed"

        result = pg.constraint_probes(FakePsql(), "new_db")
        self.assertGreaterEqual(len(result), 10)
        for sql in statements:
            self.assertTrue(sql.startswith("BEGIN;"))
            self.assertIn("ROLLBACK;", sql)
            self.assertNotIn("COMMIT;", sql)
            self.assertIn("GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE", sql)
            self.assertIn("Expected rejection did not occur", sql)

    def test_failed_run_replaces_stale_success_without_secret_in_report(self):
        report = self.root / "report.json"
        report.write_text('{"status":"passed"}', encoding="utf-8")
        argv = ["--user", "test_user", "--database", "new_db", "--stage-dir", str(self.root),
                "--report", str(report)]
        with patch.object(pg, "run", side_effect=ValueError("secret-text")):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                pg.main(argv)
        saved = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertNotIn("secret-text", report.read_text(encoding="utf-8"))

    def test_preflight_failure_happens_before_database_access(self):
        args = argparse_args(self.root)
        with patch.object(pg, "verify", side_effect=ValueError("bad CSV")), patch.object(pg, "Psql") as client:
            with self.assertRaisesRegex(ValueError, "bad CSV"):
                pg.run(args)
        client.assert_not_called()

    def test_existing_database_failure_never_applies_schema_or_resets_data(self):
        args = argparse_args(self.root)
        (self.root / "manifest.json").write_text("{}", encoding="utf-8")
        with patch.object(pg, "verify", return_value={}), patch.object(pg, "Psql") as client:
            client.return_value.version.return_value = "psql (PostgreSQL) 15.19"
            client.return_value.json.return_value = {"version_num": 150019}
            client.return_value.execute.side_effect = ValueError("database already exists")
            with self.assertRaisesRegex(ValueError, "already exists"):
                pg.run(args)
        self.assertEqual(client.return_value.execute.call_count, 1)
        sql = client.return_value.execute.call_args.args[1]
        self.assertTrue(sql.startswith('CREATE DATABASE "new_db"'))
        self.assertNotIn("DROP", sql)
        self.assertNotIn("CREATE SCHEMA", sql)


def argparse_args(root):
    from argparse import Namespace
    return Namespace(database="new_db", maintenance_db="postgres", stage_dir=root, root=root,
                     manifest=None, psql="psql", host="127.0.0.1", port=55432, user="test_user")


if __name__ == "__main__":
    unittest.main()
