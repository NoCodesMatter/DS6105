import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_indexes as runner


class IndexExperimentTests(unittest.TestCase):
    def test_finds_indexes_in_nested_parallel_and_bitmap_plans(self):
        # Inspecting only the root node would miss this bitmap index scan.
        plan = {"Plan": {"Node Type": "Gather", "Plans": [
            {"Node Type": "Bitmap Heap Scan", "Plans": [
                {"Node Type": "Bitmap Index Scan", "Index Name": "idx_selected"}]}]}}
        self.assertEqual(runner.plan_indexes(plan), {"idx_selected"})

    def test_unexpected_index_is_rejected_even_if_count_matches(self):
        reference = {field: {} for field in ("settings", "table_counts", "source_counts", "views", "functions")}
        reference.update(server_version="fixture", schema_comment="fixture", indexes=["constraint index fixture"])
        actual = dict(reference, database="scratch", indexes=["constraint index fixture", "CREATE INDEX idx_unexpected ON t (x)"])
        with self.assertRaisesRegex(ValueError, "Unexpected optional index configuration"):
            runner.check_metadata(actual, reference, ["idx_selected"], "scratch")

    def test_refuses_to_run_against_official_baseline_database(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            runner.common.write_json(directory / "manifest.json", {
                "status": "complete", "measurement_count": 150, "stages": [{"database": "official"}]})
            output = directory / "output"
            with self.assertRaisesRegex(ValueError, "refusing to modify a baseline database"):
                runner.prepare(output, directory, "official")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
