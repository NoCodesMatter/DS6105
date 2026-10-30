"""Task 4: measure Lu's indexes separately and together on a dedicated size-5 copy.

Use the accepted Task 3 baseline's frozen SQL and original size-5 timings.
One fresh unindexed control is saved separately; it does not replace Task 3 data.
"""
from __future__ import annotations

import argparse
import collections
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import subprocess

import run_baseline as common

ROOT = common.ROOT
FIELDS = ["experiment_utc", "database", "dataset_stage", "server_version", "transaction_count",
          "database_size_bytes", "index_config", "query_id", "run_number", "runtime_ms",
          "result_rows", "plan_uses_index", "query_sha256", "work_mem", "jit", "measurement_origin"]


def load_indexes(path):
    sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    indexes = {}
    for statement in (s.strip() for s in sql.split(";")):
        if not statement:
            continue
        match = re.fullmatch(r"CREATE INDEX (\w+)\s+ON housing\.\w+\s*\([^;]+\)", statement, re.I)
        common.require(match is not None, "Unsupported index statement; review the candidate SQL")
        name = match.group(1)
        common.require(name not in indexes, "Duplicate index name")
        indexes[name] = statement + ";"
    common.require(len(indexes) == 5, "Expected Lu's five reviewed candidate indexes")
    return indexes


def plan_indexes(value):
    if isinstance(value, dict):
        found = {value["Index Name"]} if "Index Name" in value else set()
        for nested in value.values():
            found.update(plan_indexes(nested))
        return found
    if isinstance(value, list):
        return set().union(*(plan_indexes(v) for v in value))
    return set()


def check_metadata(actual, reference, selected, database):
    common.require(actual["database"] == database, "Wrong indexed experiment database")
    for field in ("server_version", "settings", "schema_comment", "table_counts", "source_counts", "views", "functions"):
        common.require(actual[field] == reference[field], f"Task 3/4 metadata mismatch: {field}")
    original = set(reference["indexes"])
    current = set(actual["indexes"])
    common.require(original <= current, "A baseline constraint index changed or disappeared")
    extra = current - original
    names = {re.match(r"CREATE INDEX (\w+)", definition).group(1)
             for definition in extra if re.match(r"CREATE INDEX (\w+)", definition)}
    common.require(len(extra) == len(selected) and names == set(selected), "Unexpected optional index configuration")


def official_rows(baseline, manifest):
    with (baseline / "task3_raw.csv").open(encoding="utf-8", newline="") as source:
        rows = [r for r in csv.DictReader(source) if r["dataset_stage"] == "stage5" and r["index_config"] == "baseline"]
    groups = collections.defaultdict(list)
    for row in rows:
        common.require(int(row["transaction_count"]) == 989158, "Baseline is not the full-size stage")
        common.require(row["query_sha256"] == manifest["query_sha256"][row["query_id"]], "Baseline query hash mismatch")
        groups[row["query_id"]].append(int(row["run_number"]))
    common.require(set(groups) == {f"Q{i}" for i in range(1, 7)} and
                   all(sorted(runs) == [1, 2, 3, 4, 5] for runs in groups.values()), "Incomplete official baseline")
    return rows


def prepare(output, baseline, database):
    common.require(re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", database), "Use a simple database name")
    accepted = common.read_json(baseline / "manifest.json")
    common.require(accepted.get("status") == "complete" and accepted.get("measurement_count") == 150,
                   "Task 3 baseline is not complete")
    common.require(database not in {stage["database"] for stage in accepted["stages"]},
                   "Use a dedicated copy; refusing to modify a baseline database")
    official_rows(baseline, accepted)
    queries = {}
    for i in range(1, 7):
        path = baseline / "queries" / f"q{i}.sql"
        common.require(common.digest(path) == accepted["query_sha256"][f"Q{i}"], "Frozen baseline SQL changed")
        queries[f"Q{i}"] = path.read_bytes()
    index_file = ROOT / "sql/indexes/candidate_indexes.sql"
    indexes = load_indexes(index_file)
    common.require(not output.exists(), f"Experiment directory already exists: {output}; choose a new --out")
    output.mkdir(parents=True)
    (output / "queries").mkdir()
    for qid, body in queries.items():
        (output / "queries" / (qid.lower() + ".sql")).write_bytes(body)
    (output / "candidate_indexes.sql").write_bytes(index_file.read_bytes())
    reference = common.read_json(baseline / "stage5/metadata.json")
    common.write_json(output / "baseline_metadata.json", reference)
    configurations = [{"name": "baseline_control", "indexes": []}] + [
        {"name": name, "indexes": [name]} for name in indexes] + [{"name": "all_indexes", "indexes": list(indexes)}]
    stage5 = next(stage for stage in accepted["stages"] if stage["stage"] == "stage5")
    common.write_json(output / "manifest.json", {
        "status": "prepared", "created_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_directory": str(baseline), "baseline_manifest_sha256": common.digest(baseline / "manifest.json"),
        "database": database, "query_sha256": accepted["query_sha256"], "query_rows": stage5["query_rows"],
        "candidate_indexes_sha256": common.digest(output / "candidate_indexes.sql"),
        "configurations": configurations, "runs": 5, "warmups": 1,
        "method": accepted["method"], "cache_protocol": accepted["cache_protocol"],
        "client_environment": common.client_environment(), "runner_sha256": common.digest(__file__),
        "shared_helpers_sha256": common.digest(common.__file__),
    })
    analyze = [f"ANALYZE housing.{table};" for table in common.TABLES]
    script = ["\\set ON_ERROR_STOP on", "\\pset format unaligned", "\\pset tuples_only on", "\\pset pager off",
              "SET client_encoding = 'UTF8';", "SET work_mem = '64MB';", "SET jit = off;",
              "SET statement_timeout = '10min';",
              "DO $$ BEGIN IF EXISTS (SELECT FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid "
              "JOIN pg_namespace n ON n.oid=t.relnamespace LEFT JOIN pg_constraint c ON c.conindid=i.indexrelid "
              "WHERE n.nspname='housing' AND c.oid IS NULL) THEN "
              "RAISE EXCEPTION 'Experiment copy already has optional indexes'; END IF; END $$;"]
    for table, expected in reference["table_counts"].items():
        script.append(f"DO $$ BEGIN IF (SELECT count(*) FROM housing.{table}) <> {expected} THEN "
                      f"RAISE EXCEPTION 'Wrong size-5 count: {table}'; END IF; END $$;")
    for configuration in configurations:
        name, selected = configuration["name"], configuration["indexes"]
        directory = output / name
        directory.mkdir()
        script += [f"\\echo Configuration: {name}"]
        script += [indexes[index] for index in selected]
        script += analyze
        script += ["BEGIN;", "LOCK TABLE " + ", ".join("housing." + t for t in common.TABLES) + " IN SHARE MODE;",
                   "\\o " + common.quote((directory / "metadata.json").as_posix()), common.metadata_sql(), "\\o"]
        for qid, body_bytes in queries.items():
            body = body_bytes.decode("utf-8").strip()
            script.append(f"\\echo {name} {qid}: warm-up then 5 measured runs")
            for run in range(6):
                filename = f"{qid.lower()}_warmup.json" if run == 0 else f"{qid.lower()}_run{run}.json"
                script += ["\\o " + common.quote((directory / filename).as_posix()),
                           "EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)\n" + body, "\\o"]
            # Check complete result values AFTER timing, so this extra execution
            # does not change the one-warm-up protocol before recorded runs.
            script += ["\\o " + common.quote((directory / (qid.lower() + "_result.json")).as_posix()),
                       "WITH checked_result AS (\n" + body.rstrip(";") + "\n)\n"
                       "SELECT json_build_object('rows', count(*), 'result_md5', "
                       "md5(COALESCE(jsonb_agg(to_jsonb(checked_result) ORDER BY to_jsonb(checked_result)::text COLLATE \"C\"), "
                       "'[]'::jsonb)::text)) FROM checked_result;", "\\o"]
        script += ["COMMIT;"]
        script += [f"DROP INDEX housing.{index};" for index in selected]
        script += analyze
        script.append(f"\\echo {name} completed")
    (output / "run.sql").write_text("\n".join(script) + "\n", encoding="utf-8")


def collect(output):
    manifest = common.read_json(output / "manifest.json")
    baseline = Path(manifest["baseline_directory"])
    common.require(common.digest(baseline / "manifest.json") == manifest["baseline_manifest_sha256"],
                   "Accepted baseline manifest changed")
    reference = common.read_json(output / "baseline_metadata.json")
    baseline_manifest = common.read_json(baseline / "manifest.json")
    official = official_rows(baseline, baseline_manifest)
    common.require(common.digest(output / "candidate_indexes.sql") == manifest["candidate_indexes_sha256"],
                   "Candidate index snapshot changed")
    for i in range(1, 7):
        common.require(common.digest(output / "queries" / f"q{i}.sql") == manifest["query_sha256"][f"Q{i}"],
                       "Frozen query snapshot changed")
    measured, controls, fingerprints = [], [], {}
    candidates = set().union(*(set(c["indexes"]) for c in manifest["configurations"]))
    for configuration in manifest["configurations"]:
        name, selected = configuration["name"], configuration["indexes"]
        directory = output / name
        metadata = common.read_json(directory / "metadata.json")
        check_metadata(metadata, reference, selected, manifest["database"])
        for i in range(1, 7):
            qid = f"Q{i}"
            fingerprint = common.read_json(directory / f"q{i}_result.json")
            common.require(fingerprint["rows"] == manifest["query_rows"][i - 1], "Query output count changed")
            if not selected:
                fingerprints[qid] = fingerprint
            else:
                common.require(fingerprint == fingerprints[qid], f"Indexed query results differ: {name} {qid}")
            for run in range(6):
                filename = f"q{i}_warmup.json" if run == 0 else f"q{i}_run{run}.json"
                plan = common.read_json(directory / filename)[0]
                runtime = plan["Execution Time"]
                common.require(isinstance(runtime, (int, float)) and math.isfinite(runtime) and runtime > 0,
                               f"Invalid runtime: {name} {filename}")
                common.require(plan["Plan"]["Actual Rows"] == manifest["query_rows"][i - 1], "Plan row count changed")
                used = plan_indexes(plan) & candidates
                common.require(used <= set(selected), "Plan uses an unexpected candidate index")
                if not run:
                    continue
                row = dict(zip(FIELDS, (metadata["captured_utc"], manifest["database"], "stage5", metadata["server_version"],
                           989158, metadata["database_size_bytes"], name, qid, run, runtime, plan["Plan"]["Actual Rows"],
                           ";".join(sorted(used)), manifest["query_sha256"][qid], metadata["settings"]["work_mem"],
                           metadata["settings"]["jit"], "task4_control" if not selected else "task4_indexed")))
                (measured if selected else controls).append(row)
    common.require(len(measured) == 180 and len(controls) == 30, "Incomplete indexed experiment")
    for row in official:
        row["measurement_origin"] = "original_task3_baseline"
    for filename, rows in (("task4_raw.csv", official + measured), ("control_raw.csv", controls)):
        with (output / filename).open("x", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    manifest.update(status="complete", indexed_measurement_count=180, control_measurement_count=30,
                    comparison_csv_rows=210, query_results_equal=True, completed_utc=datetime.now(timezone.utc).isoformat())
    common.write_json(output / "manifest.json", manifest)
    print(f"COMPLETE: 180 indexed measurements + 30 control measurements. Comparison: {output / 'task4_raw.csv'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "ops/benchmark/results/task3_baseline_01")
    parser.add_argument("--db", default="sd6105_stage5_indexed")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--psql", default="psql")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    output = args.out.resolve()
    if args.collect_only:
        common.require(not args.prepare_only, "Choose prepare-only or collect-only")
        collect(output)
        return
    prepare(output, args.baseline.resolve(), args.db)
    print(f"Prepared index experiment: {output / 'run.sql'}", flush=True)
    if args.prepare_only:
        print("No database connection, index creation or timing executed.", flush=True)
        return
    command = [args.psql, "-X", "-q", "-h", args.host, "-p", str(args.port), "-U", args.user,
               "-d", args.db, "-v", "ON_ERROR_STOP=1", "-L", str(output / "psql.log"), "-f", str(output / "run.sql")]
    completed = subprocess.run(command)
    common.require(completed.returncode == 0,
                   "psql failed; preserve this incomplete experiment. The dedicated copy may retain candidate indexes; inspect before rerunning.")
    collect(output)


if __name__ == "__main__":
    main()
