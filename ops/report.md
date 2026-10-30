# Database population and performance analysis

This report analyses database population, baseline query performance and index effects across
five cumulative datasets, using experiments completed on 30 October 2026.

## Task 2: database population

The experiment used the frozen 18 October 2026 HDB snapshot and schema contract 1.0.0. HDB and
spatial producers independently verified their output CSVs before loading. The loader checked
manifest versions, the spatial-to-HDB manifest link, exact CSV headers and SHA-256 checksums.
Stable upstream IDs were preserved. The coordinate-enriched building CSV came from the spatial
stage; town, flat and transaction data came from the HDB stage, and hawker/distance data from
the spatial stage.

Each stage used a new database and loaded all six tables in foreign-key-safe order: town,
hdb_building, hdb_flat, resale_transaction, hawker_centre, building_hawker. Explicit COPY column
lists, UTF-8 encoding, HEADER MATCH and unquoted empty-field NULLs preserved the data contract.
Imports, exact table counts and the shared loaded-data validator ran inside a single transaction.
Any SQL error stopped psql and rolled back the stage; successful imports ended with COMMIT.
ANALYZE prepared planner statistics outside timed measurements. Existing data were not silently
merged or skipped.

| Stage | Cumulative HDB source labels | Transactions | Buildings | Flat profiles | Distance pairs | Measured database bytes |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2015_2016 | 37,153 | 7,921 | 28,725 | 821,912 | 121,902,771 |
| 2 | +2012_03_2014 | 89,356 | 8,431 | 57,175 | 874,640 | 146,822,835 |
| 3 | +2017_onwards | 332,311 | 9,827 | 116,466 | 1,019,616 | 233,543,347 |
| 4 | +1990_1999 | 619,507 | 10,018 | 134,795 | 1,021,800 | 303,937,203 |
| 5 | +2000_2012_02 | 989,158 | 10,024 | 147,045 | 1,022,424 | 391,894,707 |

Each stage retained the prescribed 107 hawker centres, of which 104 had coordinates and 81 had
fresh-market stalls (all 81 geocoded). The largest stage had 9,831 geocoded buildings and
193 buildings without accepted coordinates. Null locations were reported, retained and excluded
from distance pairs rather than assigned false zero coordinates. Spatial validation checked the
complete geocoded-building × geocoded-hawker matrix and distance agreement with the SQL function.

The historical HDB files include 51 transactions with unresolved lease values at full size
(36 already present at stage 4). These were retained as NULL with lease_basis=unknown. Q2's
unknown bucket conserved all transaction counts. The frozen proximity rules were near [0,500),
medium [500,1000), far [1000,2000] metres; beyond 2,000 m the class was NULL. Missing coordinates
and out-of-range distances are documented coverage limitations, not silently deleted sales.

All five imports committed successfully. Q1–Q6 were executed on every stage before benchmarking.
Q5's fixed budget selected 9/26, 11/26, 20/26, 4/27 and 2/27 towns at stages 1–5 respectively.
The consolidated and individual SQL scripts were checked for matching query text. Q1's fixed
2014–2016 window has only 2015–2016 source coverage at stage 1 and complete coverage from stage 2.

Evidence: [stage manifest](manifests/stages.json), [query checks](evidence/query_review.json),
stage loading/query logs under [evidence](evidence/), and [reproduction guide](README.md).

## Task 3: measurement method and baseline observations

The local server was PostgreSQL 17.11, 64-bit Windows, on Windows 11 with an Intel Core i7-12700H
(14 cores, 20 logical processors) and 16,962,281,472 bytes of physical RAM. The client used Python
3.12.10. work_mem was fixed at 64 MB, shared_buffers was 128 MB, jit was off, and
max_parallel_workers_per_gather was 2. Server and planner settings were captured separately for
every stage and checked for equality. Actual database view/function/index definitions and
source counts were also compared across stages. PRIMARY KEY and UNIQUE indexes formed part of
the baseline; additional indexes were rejected before baseline timing.

Runtime was the server-side Execution Time reported by EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON),
excluding planning and client transfer. Stages ran in increasing size and queries in Q1–Q6 order.
Each query had one unrecorded warm-up followed by five recorded runs. No cache reset was performed:
these are warmed-cache measurements. A table SHARE lock blocked concurrent data/index changes
while each stage was measured. The collection step checked query hashes, row counts, complete
run numbering and comparable settings before accepting all 150 original observations.

| Stage | Q1 mean ms | Q2 mean ms | Q3 mean ms | Q4 mean ms | Q5 mean ms | Q6 mean ms |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 22.224 | 45.720 | 12.861 | 389.632 | 522.729 | 236.718 |
| 2 | 35.011 | 111.186 | 27.706 | 556.897 | 703.147 | 390.498 |
| 3 | 98.284 | 508.526 | 164.244 | 826.361 | 845.062 | 1,073.500 |
| 4 | 113.084 | 1,132.475 | 290.632 | 1,193.627 | 965.978 | 1,986.140 |
| 5 | 119.328 | 2,118.625 | 409.603 | 1,631.019 | 1,261.557 | 3,525.562 |

These means summarize five original observations per cell. The [raw CSV](benchmark/results/task3_baseline_01/task3_raw.csv)
and [experiment manifest](benchmark/results/task3_baseline_01/manifest.json) are authoritative.
Q4/Q5 already have substantial stage-1 cost because the spatial matrix contains 821,912 pairs
despite only 37,153 transactions. By stage 5, Q6 is the slowest measured query. A saved stage-5
Q2 plan uses an external merge sort with 52,232 kB of disk sort space; Q6's saved plan shows
66,632 kB. These plan observations support discussion of aggregation/sort costs but do not alone
establish a general complexity model.

## Task 4: indexed execution and comparison

After accepting the full baseline, the largest database was copied to a dedicated
sd6105_stage5_indexed database. The five candidate indexes were evaluated individually and then
all together. Each configuration used create index → ANALYZE → one warm-up plus five runs of
each query → drop index → ANALYZE. The frozen Task 3 query snapshots and the same timing method
and settings were used. Collection checked server settings, source counts, view/function
definitions and baseline constraint indexes against the original largest-stage metadata.

Six indexed configurations produced 180 new timings. A separate initial unindexed control
produced 30 additional observations. The [comparison CSV](benchmark/results/task4_indexes_02/task4_raw.csv)
contains 210 rows: the 30 original Task 3 size-5 baseline rows and 180 indexed observations.
The reused 30 baseline rows are not new observations. Across both tasks, including the separate
control, 360 new timings were collected: 150 + 180 + 30.

Saved plans identify candidate indexes actually used. After each query's timed runs, an extra
untimed execution generated a deterministic digest of its sorted complete result multiset,
preserving duplicates. Every indexed configuration matched the unindexed control's digest and
row count. Candidate indexes were dropped at the end of successful SQL execution.

| Configuration | Query | Original baseline mean ms | Indexed mean ms | Runtime change | Candidate index used |
|---|---|---:|---:|---:|---|
| sale_month | Q1 | 119.328 | 94.033 | −21.2% | Yes |
| flat_id | Q4 | 1,631.019 | 3,757.134 | +130.4% | Yes |
| flat_type/building_id | Q3 | 409.603 | 365.897 | −10.7% | Yes |
| building_id/distance_m/hawker_id | Q4 | 1,631.019 | 1,443.063 | −11.5% | Yes |
| building_id/distance_m/hawker_id | Q5 | 1,261.557 | 1,004.034 | −20.4% | Yes |
| town_name | Q1–Q6 | — | — | No candidate-index usage observed | No |
| All five indexes | Q4 | 1,631.019 | 3,570.435 | +118.9% | flat_id and building/distance |

The flat_id Q4 plan includes multiple nested-loop levels and 67,182 loops of its resale
transaction index scan. Thus an index being used did not guarantee faster execution. The all-index
configuration also regressed on Q4. These workload-specific results support evaluating index
usefulness per query rather than retaining every candidate.

The [fresh unindexed control](benchmark/results/task4_indexes_02/control_raw.csv) differed from
the original baseline means by +11.3%, +6.7%, +8.5%, +0.2%, −4.4% and −1.7% for Q1–Q6 respectively.
This is one observed control comparison, not a confidence interval or a universal noise threshold.
Short-query changes and modest gains require cautious interpretation. ANALYZE resamples statistics,
the workload order was fixed, and cache/scheduling/power conditions can affect timings. Five repeated
runs and one control do not establish statistical significance or performance on other hardware.

The earlier 746,203-row scratch experiment used older view definitions and a different dataset
size. Its runtimes are not directly comparable with these 989,158-row, contract-1.0.0 measurements.
