# Task 3 baseline measurements — Sun NengKe

Python 3.10+ standard library, PostgreSQL and psql 15+. Use schema contract 1.0.0.
The five databases must already pass the [loading checks](../loading/README.md) and
the reviewed [Q1–Q6 queries](../../sql/queries/README.md). The local database names,
transaction counts and reviewed result row counts are recorded in [stages.json](stages.json).

## Run from the repository root

```powershell
python ops/benchmark/run_baseline.py --psql 'E:\NTU\DataSystem\project\PostgreSQL\17\bin\psql.exe' --out ops/benchmark/results/task3_baseline_01
```

Enter the PostgreSQL password at the console. psql reuses connection parameters when switching
between databases on the same server. No password is stored in files or passed on the command line.
Defaults: localhost, port 5432, user postgres. Override with `--host`, `--port`, `--user`.
Use a new output name for a rerun: previous runs are never overwritten.

## Protocol

- Stages run in increasing size; Q1–Q6 run in numeric order within each stage.
- Per query: one unrecorded warm-up followed by exactly five recorded executions.
- Time is PostgreSQL `Execution Time` in milliseconds from
  `EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)`, matching Lu's timing method. Planning and
  client transfer are excluded. This is a warmed-cache protocol, not a cold-cache experiment;
  no operating-system or PostgreSQL cache reset is performed.
- `work_mem=64MB`, `jit=off`, `statement_timeout=10min` are set separately on every connection.
  Other planner/server settings are recorded and must match across stages. Use the same settings,
  SQL and schema for Task 4. PRIMARY KEY and UNIQUE indexes remain part of the baseline.
- A table SHARE lock is held for each stage, blocking other sessions' data/index changes during
  that stage's measurements. The experiment itself performs SELECT/EXPLAIN only. Extra indexes
  not owned by constraints are rejected before timing. Do not run another benchmark or heavy
  workload concurrently; keep the machine's power mode consistent.
- Exact table counts are checked before timing. Source counts, actual views/functions/index
  definitions and settings are compared during collection. Every execution's result row count
  must match the previously reviewed query results. This guards output shape, not complete SQL
  semantic correctness; LI remains responsible for query meaning.
- `experiment_utc` in the CSV is the per-stage metadata capture timestamp.

## Outputs

`COMPLETE: 150 measurements` is printed only after all five stages and all checks pass.

- `task3_raw.csv`: 150 original observations, compatible with Lu's plotting program. No averaged
  or synthetic times are substituted for measurements.
- `manifest.json`: stage/source manifests, query hashes, source versions, client CPU/RAM, method,
  runner hash and status. Client hardware describes the server only for a local connection.
- `queries/`: exact frozen SQL used by this experiment.
- `stage1/` through `stage5/`: server metadata plus 30 measured plans and six warm-up plans each.
- `run.sql`, `psql.log`: reproducible psql workload and execution evidence.

A failed experiment remains incomplete, retains its evidence and does not publish `task3_raw.csv`.
For a new measurement series, choose a new `--out` directory. `--stage stage1` runs one stage
(30 observations); it does not establish completion of the five-stage assignment requirement.

## Preparation and recovery

```powershell
# Generate and inspect all input snapshots and SQL, without connecting or measuring:
python ops/benchmark/run_baseline.py --out .hdb-qa/baseline_preflight_01 --prepare-only

# Validate and collect a complete SQL run if Python was interrupted after psql finished:
python ops/benchmark/run_baseline.py --out <existing-experiment-directory> --collect-only

python -m unittest discover -s ops/benchmark/tests -v
```

Do not use `--collect-only` to reuse partial observations across different measurement series.
The raw plans must form one complete, unchanged experiment. The collection tests use temporary
synthetic fixtures only; those fixtures are not experimental evidence.

Task 4's indexed measurements and Lu's charts follow after the 150-row baseline is accepted.

## Task 4: individual indexes and combined configuration

First create the dedicated `sd6105_stage5_indexed` database using
[create_index_database.sql](../loading/create_index_database.sql). Then run:

```powershell
python ops/benchmark/run_indexes.py --psql 'E:\NTU\DataSystem\project\PostgreSQL\17\bin\psql.exe' --out ops/benchmark/results/task4_indexes_01
```

This uses Lu's existing [candidate_indexes.sql](../../sql/indexes/candidate_indexes.sql) without
changing it: five individual configurations and one configuration containing all five indexes.
Only the dedicated copy is modified. The runner refuses any database listed in the accepted
Task 3 experiment. Override the copy name with `--db` if necessary.

Each configuration follows create index → ANALYZE → one warm-up + five measured runs per query →
drop index → ANALYZE. Index creation completes before timing begins. Timing uses exactly the Task 3
mechanism, frozen SQL and explicit settings. Table counts, source counts, server settings,
view/function definitions and baseline constraint indexes are checked against the accepted stage 5.
Query snapshots are copied byte-for-byte from the accepted experiment, rather than from potentially
edited working SQL. Candidate index definitions are also frozen in the experiment directory.

The initial unindexed control runs on the copy and is saved separately in `control_raw.csv` (30
observations), so timing drift can be inspected. It does not replace or modify the official baseline.
Six indexed configurations produce 180 new observations. `task4_raw.csv` contains these 180 plus
the 30 original Task 3 stage-5 observations: **210 comparison rows**, compatible with Lu's plotter.
`measurement_origin` identifies copied baseline rows and new indexed/control observations.

Every execution plan is saved, including actual index names used. After each query's timed runs,
an additional untimed execution computes a deterministic digest of its sorted complete result
multiset (preserving duplicate rows). The digest and row count must match the unindexed control for
every configuration. This is an operational result-equivalence check; timing observations remain
server-side execution time with result transfer excluded.

`COMPLETE: 180 indexed measurements + 30 control measurements` appears only when all files and
checks pass. Outputs also include per-configuration metadata, result digests and plans; exact SQL;
candidate definitions; runner/client provenance; and a manifest linking the accepted baseline.

Preparation can be inspected with `--prepare-only`; existing complete SQL runs can be collected
with `--collect-only`, as for the baseline runner. Use a new `--out` for every rerun. On successful
SQL execution all candidate indexes are removed. If SQL fails, the experiment stays incomplete and
the dedicated copy may retain indexes; preserve the evidence and inspect the copy before rerunning.
