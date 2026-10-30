"""Reject incomplete or incomparable experiments before publishing raw CSVs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("run_baseline", Path(__file__).resolve().parents[1] / "run_baseline.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CollectionTests(unittest.TestCase):
    def fixture(self, directory, stage_count=1):
        # Synthetic plans test validation without PostgreSQL or real timing data.
        (directory / "queries").mkdir()
        hashes = {}
        for i in range(1, 7):
            path = directory / "queries" / f"q{i}.sql"
            path.write_text("SELECT 1;\n", encoding="utf-8")
            hashes[f"Q{i}"] = runner.digest(path)
        stages = []
        for number in range(1, stage_count + 1):
            stage = {"stage": f"stage{number}", "database": f"test_stage{number}",
                     "table_counts": {"resale_transaction": number}, "source_counts": {"test_source": number},
                     "transaction_count": number, "query_rows": [1] * 6}
            stages.append(stage)
            folder = directory / stage["stage"]
            folder.mkdir()
            runner.write_json(folder / "metadata.json", {
                "database": stage["database"], "table_counts": stage["table_counts"],
                "source_counts": stage["source_counts"], "server_version": "test fixture only",
                "schema_comment": "Housing schema contract 1.0.0; frozen at Gate 0 for the Task 3 baseline",
                "settings": {"work_mem": "65536", "jit": "off"}, "views": {}, "functions": {}, "indexes": [],
                "captured_utc": "test fixture only", "database_size_bytes": 1024})
            for i in range(1, 7):
                for run in range(6):
                    filename = f"q{i}_warmup.json" if run == 0 else f"q{i}_run{run}.json"
                    runner.write_json(folder / filename, [{"Execution Time": 1.0, "Plan": {"Actual Rows": 1}}])
        runner.write_json(directory / "manifest.json", {"stages": stages, "query_sha256": hashes})

    def test_missing_last_measurement_does_not_publish_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.fixture(directory)
            (directory / "stage1/q6_run5.json").unlink()
            with self.assertRaises(FileNotFoundError):
                runner.collect(directory)
            self.assertFalse((directory / "task3_raw.csv").exists())

    def test_settings_drift_between_stages_rejects_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.fixture(directory, 2)
            path = directory / "stage2/metadata.json"
            metadata = runner.read_json(path)
            metadata["settings"]["shared_buffers"] = "different"
            runner.write_json(path, metadata)
            with self.assertRaisesRegex(ValueError, "differ across stages"):
                runner.collect(directory)
            self.assertFalse((directory / "task3_raw.csv").exists())

    def test_changed_query_output_rejects_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.fixture(directory)
            runner.write_json(directory / "stage1/q5_run3.json",
                              [{"Execution Time": 1.0, "Plan": {"Actual Rows": 0}}])
            with self.assertRaisesRegex(ValueError, "output row count changed"):
                runner.collect(directory)
            self.assertFalse((directory / "task3_raw.csv").exists())

    def test_changed_frozen_sql_rejects_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.fixture(directory)
            (directory / "queries/q1.sql").write_text("SELECT 2;", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "query snapshot changed"):
                runner.collect(directory)
            self.assertFalse((directory / "task3_raw.csv").exists())


if __name__ == "__main__":
    unittest.main()
