#!/usr/bin/env python3
"""Per-index effect experiment for Task 4 (Lu Wenrui).

For each configuration (baseline, each candidate index alone, all indexes):
  create index(es) -> ANALYZE -> for each query: 1 warm-up + N timed runs -> drop.

Timing = PostgreSQL server-side "Execution Time" from
EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON), so client transfer is excluded and
per-node timing overhead is minimal. The same method must be used for the
Task 3 baseline so the comparison is like-for-like (agree this with Sun).

Uses only the standard library plus the `psql` client.

Example:
  python analysis/index_experiment.py --db scratch_stage5 --runs 5 \
      --out analysis/results/index_experiment_raw.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY_DIR = ROOT / "sql" / "queries"
INDEX_FILE = ROOT / "sql" / "indexes" / "candidate_indexes.sql"


def psql(db: str, sql: str, args) -> str:
    cmd = ["psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-d", db]
    if args.host:
        cmd += ["-h", args.host]
    if args.port:
        cmd += ["-p", str(args.port)]
    if args.user:
        cmd += ["-U", args.user]
    res = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"psql failed:\n{res.stderr}")
    return res.stdout


def load_indexes() -> dict[str, str]:
    """Return {index_name: CREATE INDEX statement} from candidate_indexes.sql."""
    text = re.sub(r"--[^\n]*", "", INDEX_FILE.read_text(encoding="utf-8"))
    out = {}
    for stmt in (s.strip() for s in text.split(";")):
        m = re.match(r"CREATE INDEX (\w+)", stmt, re.I)
        if m:
            out[m.group(1)] = stmt + ";"
    return out


def load_queries() -> dict[str, str]:
    qs = {}
    for i in range(1, 7):
        body = (QUERY_DIR / f"q{i}.sql").read_text(encoding="utf-8").strip().rstrip(";")
        qs[f"Q{i}"] = body
    return qs


def time_query(db, body, args) -> tuple[float, int]:
    out = psql(db, f"EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) {body};", args)
    plan = json.loads(out)[0]
    return plan["Execution Time"], plan["Plan"].get("Actual Rows", -1)


def plan_uses(db, body, index, args) -> bool:
    out = psql(db, f"EXPLAIN (COSTS OFF) {body};", args)
    return index in out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--user")
    ap.add_argument("--stage", help="dataset_stage label written to the CSV (default: --db)")
    ap.add_argument("--only", help="comma-separated index names to test (default all)")
    args = ap.parse_args()

    indexes = load_indexes()
    if args.only is not None:  # --only "" -> baseline only
        indexes = {k: v for k, v in indexes.items() if k in args.only.split(",")}
    queries = load_queries()

    existing = psql(args.db, "SELECT indexname FROM pg_indexes WHERE schemaname='housing';", args).split()
    clash = [i for i in indexes if i in existing]
    if clash:
        sys.exit(f"Refusing to run: candidate indexes already exist {clash}. Use a clean database.")

    tx = int(psql(args.db, "SELECT count(*) FROM housing.resale_transaction;", args))
    size = int(psql(args.db, "SELECT pg_database_size(current_database());", args))
    version = psql(args.db, "SHOW server_version;", args).strip()

    configs = [("baseline", [])] + [(name, [name]) for name in indexes]
    if len(indexes) > 1:
        configs.append(("all_indexes", list(indexes)))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fields = ["experiment_utc", "database", "dataset_stage", "server_version", "transaction_count",
              "database_size_bytes", "index_config", "query_id", "run_number",
              "runtime_ms", "result_rows", "plan_uses_index"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for cfg, idx in configs:
            for name in idx:
                psql(args.db, indexes[name], args)
            psql(args.db, "ANALYZE;", args)
            for qid, body in queries.items():
                used = ";".join(i for i in idx if plan_uses(args.db, body, i, args)) if idx else ""
                time_query(args.db, body, args)  # warm-up, not recorded
                for run in range(1, args.runs + 1):
                    ms, rows = time_query(args.db, body, args)
                    w.writerow(dict(experiment_utc=stamp, database=args.db, dataset_stage=args.stage or args.db, server_version=version,
                                    transaction_count=tx, database_size_bytes=size,
                                    index_config=cfg, query_id=qid, run_number=run,
                                    runtime_ms=round(ms, 3), result_rows=rows,
                                    plan_uses_index=used))
                    fh.flush()
                print(f"{cfg:28s} {qid}  used=[{used}]", flush=True)
            for name in idx:
                psql(args.db, f"DROP INDEX housing.{name};", args)
            psql(args.db, "ANALYZE;", args)


if __name__ == "__main__":
    main()
