"""Task 3: one warm-up and five server-side timings per query at each stage.

Uses Python's standard library and psql; the password is entered in psql.
All generated files live in a new experiment directory. SQL/source snapshots,
PostgreSQL settings, execution plans and raw measurements are retained.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TABLES = ("town", "hdb_building", "hdb_flat", "resale_transaction", "hawker_centre", "building_hawker")
SETTINGS = (
    "work_mem", "shared_buffers", "jit", "max_parallel_workers_per_gather",
    "max_parallel_workers", "max_worker_processes", "effective_cache_size",
    "random_page_cost", "seq_page_cost", "default_statistics_target",
    "enable_seqscan", "enable_indexscan", "enable_indexonlyscan", "enable_bitmapscan",
    "enable_hashjoin", "enable_mergejoin", "enable_nestloop", "track_io_timing",
    "server_encoding", "client_encoding", "block_size", "statement_timeout",
    "max_connections", "maintenance_work_mem", "temp_file_limit",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def quote(value):
    require(not any(c in value for c in "\n\r\x00"), "Invalid SQL/psql value")
    return "'" + value.replace("'", "''") + "'"


def client_environment():
    result = {"platform": platform.platform(), "python": sys.version, "logical_cpus": os.cpu_count()}
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_physical", "available_physical", "total_pagefile", "available_pagefile",
                    "total_virtual", "available_virtual", "available_extended_virtual")]

        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result["physical_memory_bytes"] = memory.total_physical
    return result


def metadata_sql():
    settings = ",".join(quote(name) for name in SETTINGS)
    counts = " UNION ALL ".join(
        f"SELECT '{table}' AS name, count(*) AS rows FROM housing.{table}" for table in TABLES)
    return f"""SELECT json_build_object(
      'database', current_database(), 'server_version', version(),
      'captured_utc', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
      'database_size_bytes', pg_database_size(current_database()),
      'schema_comment', obj_description('housing'::regnamespace, 'pg_namespace'),
      'settings', (SELECT json_object_agg(name, setting) FROM pg_settings WHERE name IN ({settings})),
      'table_counts', (SELECT json_object_agg(name, rows) FROM ({counts}) AS counts),
      'source_counts', (SELECT json_object_agg(source_dataset, rows) FROM
          (SELECT source_dataset, count(*) AS rows FROM housing.resale_transaction GROUP BY source_dataset) AS sources),
      'indexes', (SELECT json_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid::regclass::text)
          FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
          JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='housing'),
      'views', (SELECT json_object_agg(c.relname, pg_get_viewdef(c.oid, true))
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='housing' AND c.relkind='v'),
      'functions', (SELECT json_object_agg(p.proname, pg_get_functiondef(p.oid))
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='housing')
    );"""


def prepare(output, selected):
    require(not output.exists(), f"Experiment directory already exists: {output}; choose a new --out")
    config = read_json(HERE / "stages.json")
    stages = [s for s in config["stages"] if not selected or s["stage"] == selected]
    require(stages, "No matching stage")
    queries = {f"Q{i}": (ROOT / f"sql/queries/q{i}.sql").read_text(encoding="utf-8").strip()
               for i in range(1, 7)}
    # Check stage provenance before producing any runnable experiment.
    for stage in stages:
        hdb_path = ROOT / "data/processed/hdb" / stage["directory"] / "manifest.json"
        spatial_path = ROOT / "data/processed/spatial" / stage["directory"] / "manifest.json"
        hdb, spatial = read_json(hdb_path), read_json(spatial_path)
        require(hdb["contract_version"] == spatial["contract_version"] == config["contract_version"],
                f"Contract mismatch: {stage['stage']}")
        require(spatial["hdb_stage"]["manifest_sha256"] == digest(hdb_path), "Stage provenance mismatch")
        require(hdb["accepted_records"] == stage["transaction_count"], "Unexpected transaction count")
        stage["table_counts"] = {t: (spatial if t in ("hdb_building", "hawker_centre", "building_hawker")
                                     else hdb)["tables"][t]["rows"] for t in TABLES}
        stage["source_counts"] = {s["dataset_id"]: s["rows"] for s in hdb["sources"]}
        stage["hdb_manifest_sha256"] = digest(hdb_path)
        stage["spatial_manifest_sha256"] = digest(spatial_path)
        stage["hdb_manifest"] = hdb
        stage["spatial_manifest"] = spatial
    output.mkdir(parents=True)
    (output / "queries").mkdir()
    for qid, body in queries.items():
        (output / "queries" / (qid.lower() + ".sql")).write_text(body + "\n", encoding="utf-8")
    write_json(output / "manifest.json", {
        "status": "prepared", "created_utc": datetime.now(timezone.utc).isoformat(),
        "contract_version": config["contract_version"], "client_environment": client_environment(),
        "method": "EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON): Execution Time",
        "cache_protocol": "one warm-up before five recorded runs per query; no OS/database cache reset",
        "runs": 5, "warmups": 1, "query_order": list(queries), "stages": stages,
        "query_sha256": {qid: digest(output / "queries" / (qid.lower() + ".sql")) for qid in queries},
        "schema_file_sha256": digest(ROOT / "db/schema/001_schema.sql"),
        "runner_sha256": digest(__file__),
        "server_hardware_note": "Client CPU/RAM describe the server only when using the same physical machine.",
    })
    script = ["\\set ON_ERROR_STOP on", "\\pset format unaligned", "\\pset tuples_only on",
              "\\pset pager off"]
    for stage in stages:
        directory = output / stage["stage"]
        directory.mkdir()
        script += [f"\\connect {stage['database']}", "SET client_encoding = 'UTF8';",
                   "SET work_mem = '64MB';", "SET jit = off;", "SET statement_timeout = '10min';",
                   # Block writes while checking and measuring each stage, keeping
                   # the connection's default READ COMMITTED isolation level.
                   "BEGIN;",
                   "LOCK TABLE " + ", ".join("housing." + t for t in TABLES) + " IN SHARE MODE;",
                   "DO $$ BEGIN IF EXISTS (SELECT FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid "
                   "JOIN pg_namespace n ON n.oid=t.relnamespace LEFT JOIN pg_constraint c ON c.conindid=i.indexrelid "
                   "WHERE n.nspname='housing' AND c.oid IS NULL) THEN "
                   "RAISE EXCEPTION 'Optional indexes found: not a clean baseline'; END IF; END $$;"]
        for table, expected in stage["table_counts"].items():
            script.append(f"DO $$ BEGIN IF (SELECT count(*) FROM housing.{table}) <> {expected} THEN "
                          f"RAISE EXCEPTION 'Wrong stage table count: {table}'; END IF; END $$;")
        script += ["\\o " + quote((directory / "metadata.json").as_posix()), metadata_sql(), "\\o"]
        for qid, body in queries.items():
            script.append(f"\\echo {stage['stage']} {qid}: warm-up then 5 measured runs")
            for run in range(6):
                filename = f"{qid.lower()}_warmup.json" if run == 0 else f"{qid.lower()}_run{run}.json"
                script += ["\\o " + quote((directory / filename).as_posix()),
                           "EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)\n" + body, "\\o"]
        script += ["COMMIT;", f"\\echo {stage['stage']} completed"]
    (output / "run.sql").write_text("\n".join(script) + "\n", encoding="utf-8")
    return stages


def collect(output):
    manifest = read_json(output / "manifest.json")
    fields = ["experiment_utc", "database", "dataset_stage", "server_version", "transaction_count",
              "database_size_bytes", "index_config", "query_id", "run_number", "runtime_ms",
              "result_rows", "plan_uses_index", "query_sha256", "work_mem", "jit"]
    rows, reference = [], None
    for stage in manifest["stages"]:
        directory = output / stage["stage"]
        metadata = read_json(directory / "metadata.json")
        require(metadata["database"] == stage["database"], "Wrong database in metadata")
        require(metadata["table_counts"] == stage["table_counts"], "Database table counts do not match the stage")
        require(metadata["source_counts"] == stage["source_counts"], "Database source counts do not match the stage")
        require(metadata["schema_comment"] == "Housing schema contract 1.0.0; frozen at Gate 0 for the Task 3 baseline",
                "Unexpected database contract")
        require(metadata["settings"]["work_mem"] == "65536" and metadata["settings"]["jit"] == "off",
                "Measurement settings changed")
        # Keep schema and settings identical; only the loaded data should change.
        comparable = {k: metadata[k] for k in ("server_version", "settings", "views", "functions", "indexes")}
        require(reference is None or comparable == reference, "Database definitions or settings differ across stages")
        reference = comparable
        for i in range(1, 7):
            qid = f"Q{i}"
            snapshot = output / "queries" / f"q{i}.sql"
            require(digest(snapshot) == manifest["query_sha256"][qid], "Frozen query snapshot changed")
            for run in range(6):
                filename = f"q{i}_warmup.json" if run == 0 else f"q{i}_run{run}.json"
                plan = read_json(directory / filename)[0]
                runtime = plan["Execution Time"]
                require(isinstance(runtime, (int, float)) and math.isfinite(runtime) and runtime > 0,
                        f"Invalid runtime: {filename}")
                require(plan["Plan"]["Actual Rows"] == stage["query_rows"][i - 1],
                        f"Query output row count changed: {stage['stage']} {qid}")
                if run:
                    rows.append(dict(zip(fields, (
                        metadata["captured_utc"], stage["database"], stage["stage"], metadata["server_version"],
                        stage["transaction_count"], metadata["database_size_bytes"], "baseline", qid, run,
                        runtime, plan["Plan"]["Actual Rows"], "", manifest["query_sha256"][qid],
                        metadata["settings"]["work_mem"], metadata["settings"]["jit"]))))
    require(len(rows) == len(manifest["stages"]) * 30, "Incomplete measurements")
    # Do not publish a partial CSV if any run failed validation.
    with (output / "task3_raw.csv").open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest["status"] = "complete"
    manifest["measurement_count"] = len(rows)
    manifest["completed_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "manifest.json", manifest)
    print(f"COMPLETE: {len(rows)} measurements -> {output / 'task3_raw.csv'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New experiment directory")
    parser.add_argument("--psql", default="psql", help="psql executable path")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--stage", choices=[f"stage{i}" for i in range(1, 6)], help="Optional single-stage run")
    parser.add_argument("--prepare-only", action="store_true", help="Generate inputs/SQL without connecting")
    parser.add_argument("--collect-only", action="store_true", help="Validate and collect an existing completed SQL run")
    args = parser.parse_args()
    output = args.out.resolve()
    if args.collect_only:
        require(not args.prepare_only, "Choose prepare-only or collect-only")
        collect(output)
        return
    stages = prepare(output, args.stage)
    print(f"Prepared {len(stages)} stages. SQL: {output / 'run.sql'}", flush=True)
    if args.prepare_only:
        print("No database connection or timing executed.", flush=True)
        return
    command = [args.psql, "-X", "-q", "-h", args.host, "-p", str(args.port), "-U", args.user,
               "-d", stages[0]["database"], "-v", "ON_ERROR_STOP=1", "-L", str(output / "psql.log"),
               "-f", str(output / "run.sql")]
    # Inherit stdin so psql can read its password directly from the user's console.
    # Credentials are not passed on the command line or written into experiment files.
    completed = subprocess.run(command)
    require(completed.returncode == 0, "psql failed; experiment remains incomplete. Preserve evidence and rerun with a new --out")
    collect(output)


if __name__ == "__main__":
    main()
