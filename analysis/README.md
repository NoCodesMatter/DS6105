# Performance analysis (Lu Wenrui)

Python 3.10+, `pandas` and `matplotlib` (`pip install pandas matplotlib`), and the `psql` client.
Run everything from the repository root.

| File | What it does |
|---|---|
| `index_experiment.py` | Times Q1–Q6 for the baseline, each candidate index alone, and all indexes (1 warm-up + N runs each). Writes one CSV row per run. |
| `plot_performance.py` | Builds Task 3 summary + "database size vs runtime" charts, and Task 4 summary + "with/without index" bar charts, from raw CSVs. |
| `scratch/load_scratch_db.sh` | Loads one HDB + spatial stage into a **new scratch** database. For index exploration only; Sun's loader is the official one. |
| `results/` | Scratch raw timings and figures (not official results; see `sql/indexes/README.md`). |

## Commands

```sh
# Task 4: per-index experiment on a clean copy of the largest stage (never on the baseline DB)
python analysis/index_experiment.py --db <largest_stage_db> --stage stage5 --runs 5 --out analysis/results/task4_raw.csv

# Baseline only (no candidate indexes), e.g. to test the protocol on one stage
python analysis/index_experiment.py --db <db> --stage stage1 --only "" --runs 5 --out analysis/results/stage1_baseline.csv

# Charts and summary tables
python analysis/plot_performance.py --task3 <baseline_raw.csv> --task4 analysis/results/task4_raw.csv --outdir report/figures
```

`--host`, `--port` and `--user` are passed to `psql`. Passwords come from `pgpass` or `PGPASSWORD`.

## Raw CSV columns

`experiment_utc, database, dataset_stage, server_version, transaction_count, database_size_bytes,
index_config, query_id, run_number, runtime_ms, result_rows, plan_uses_index`

`plot_performance.py --task3` needs at least `query_id, dataset_stage, transaction_count,
run_number, runtime_ms`, so Sun's baseline CSV can be used directly if it has these columns.
It warns if any query/stage pair does not have exactly 5 runs.
