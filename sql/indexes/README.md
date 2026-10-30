# Task 4 — Index selection (Lu Wenrui)

**Status: exploratory, scratch database only.** The numbers below are not the official
Task 4 results. They come from a scratch PostgreSQL 16.15 server (2 vCPU, 7 GB RAM,
`work_mem=64MB`, `jit=off`) loaded with **746,203 transactions** (1990–2016; four of the five
HDB files). The `2017_onwards` file is missing from the frozen snapshot on this machine.
The official comparison must be repeated by Sun at the real largest stage, using the same
timing method as the Task 3 baseline.

| File | Purpose |
|---|---|
| `candidate_indexes.sql` | `CREATE INDEX` statements I1–I5 |
| `../../analysis/index_experiment.py` | Creates each index alone (then all), runs Q1–Q6 1 warm-up + 5 times, drops it |
| `../../analysis/plot_performance.py` | Summary tables and Task 3 / Task 4 charts from the raw CSVs |
| `../../analysis/results/` | Scratch raw timings and figures |

## Method

- Timing is the server-side `Execution Time` from `EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)`.
  This excludes client transfer and keeps per-node timing overhead low.
- Each configuration: create index → `ANALYZE` → for each query, one unrecorded warm-up and five
  recorded runs → drop index → `ANALYZE`. Indexes from PRIMARY KEY / UNIQUE constraints stay
  (they are part of the baseline schema).
- The script records whether the final plan actually uses the index (`plan_uses_index`).
- **Noise floor:** indexes that the planner did *not* use still moved runtimes by roughly
  −23 % to +29 % (largest on the short Q1/Q3, ±10 % on the multi-second queries). A change counts
  as real only if the index is visible in the plan **and** the result lies outside that band.

## Baseline bottlenecks (EXPLAIN ANALYZE, 746k transactions)

| Query | Baseline mean | Where the time goes |
|---|---:|---|
| Q1 | 119 ms | Parallel seq scan of `resale_transaction`; only ~6 % of rows fall in 2014–2016 |
| Q2 | 1,826 ms | `PERCENTILE_CONT` needs a full sort by town/bucket/price; spills to disk (~39 MB external merge) |
| Q3 | 485 ms | Hash joins over all transactions to keep 3-Room rows |
| Q4 | 2,770 ms | `nearest_hawker` view: sorts the whole ~886k-row `building_hawker` and calls `proximity_class()` on every row before `DISTINCT ON` (~1.4 s) |
| Q5 | 2,787 ms | Same pattern via `nearest_market_hawker` (plus join to `hawker_centre`) |
| Q6 | 3,618 ms | `PERCENTILE_CONT` sort spills to disk (~70 MB); aggregation over all `building_hawker` rows |

Scaling note: Q4 and Q5 already take ~1.3–1.5 s on stage 1 (37k transactions). Their cost is
dominated by the spatial matrix, which grows only with the number of *buildings*, not transactions.

## Per-index results (mean of 5 runs; change vs baseline)

| Index | Target | Used by planner in | Effect |
|---|---|---|---|
| **I1** `resale_transaction(sale_month)` | Q1 date window | Q1 | **Q1 −24 %** (119 → 91 ms). With all indexes Q1 is 67 ms, still using only I1. Both are below every no-effect configuration (115–154 ms): the only clear win. |
| **I2** `resale_transaction(flat_id)` | FK joins | Q4 only | No gain; Q4 +11 % (planner switched to nested loops). Hash joins over most rows are already optimal. |
| **I3** `hdb_flat(flat_type, building_id)` | Q1, Q3 type filter | Q3 | Used in Q3 but no gain (+0 %); not used in Q1. |
| **I4** `building_hawker(building_id, distance_m, hawker_id)` | `DISTINCT ON` order in Q4/Q5 views | Q4 | Q4 −12 %, inside the noise band: the sort is removed, but per-row function calls remain (see below). Not used for Q5. |
| **I5** `hdb_building(town_name)` | Q3 town join | none | Not used (table is only ~9k rows); differences are noise. |

Full numbers: `analysis/results/scratch_figures/task4_summary.csv`.

## Key finding: the view definition limits I4

The `DISTINCT ON` itself with I4 takes **163 ms** (index-only scan, no sort). Through the
`housing.nearest_hawker` view it takes **1,395 ms**. The view calls `proximity_class(distance_m)`
in the same SELECT as `DISTINCT ON`, so the function runs for all ~886k rows before duplicates are
removed. The function is `STRICT`, so PostgreSQL cannot inline it.

Moving the function call outside the `DISTINCT ON` returns **identical rows** (verified with
`EXCEPT` in both directions, 0 differences):

```sql
CREATE VIEW housing.nearest_hawker AS
SELECT building_id, hawker_id, distance_m, housing.proximity_class(distance_m) AS proximity_class
FROM (SELECT DISTINCT ON (building_id) building_id, hawker_id, distance_m
      FROM housing.building_hawker
      ORDER BY building_id, distance_m, hawker_id) s;
```

| `SELECT * FROM nearest_hawker` | Time |
|---|---:|
| Current view, no extra index | 1,362 ms |
| Rewritten view, no extra index | 459 ms |
| Rewritten view + I4 | **156 ms** (8.7× faster) |

The same rewrite applies to `nearest_market_hawker`. This is a schema change, so it needs
**WU's approval** and must be made **before** the Task 3 baseline is measured; otherwise
Task 3 and Task 4 would compare different view definitions.

## Indexes cannot fix Q2 and Q6

Both are bound by the sort for `PERCENTILE_CONT` (median), which spills to disk. No B-tree
index provides that order, because the group keys come from joined tables. Their runtime
depends on `work_mem`. Sun must record `work_mem` and keep it fixed across all runs.

## Issues for other owners

- **LI — Q5 returns 0 rows** on the 1990–2016 database. Old transactions pull every town's average
  below SGD 450,000. Check Q5 at every official stage; the brief requires some but not all towns.
- **WU — view rewrite** above (recommended before the baseline is frozen).
- **Sun — protocol:** use the same timing method for baseline and indexed runs; record
  `server_version`, `work_mem`, `shared_buffers`, `jit`, CPU/RAM; do one warm-up run.
  Expect ±10–30 % run-to-run noise (largest on short queries).
- **HE / Sun — missing source:** this machine could not obtain the frozen `2017_onwards` file
  (`d_8b84c4ee58e3cfc0ece0d773c8ca6abc`, SHA-256 `d401fc2e…`). It must be shared from the
  original snapshot.

## Proposed submission set (to confirm on the real largest stage)

1. **I1** `idx_rt_sale_month` — clear, plan-visible gain for Q1.
2. **I4** `idx_bh_building_distance` — strong gain together with the view rewrite.
3. **I2, I3, I5** — report as tested and rejected (not used, or used without measurable gain),
   with the evidence above. Negative results are valid Task 4 findings.
