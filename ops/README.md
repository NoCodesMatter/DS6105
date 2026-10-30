# Database operations and performance measurements — Sun NengKe

Schema contract **1.0.0**, PostgreSQL **17.11**, frozen HDB snapshot **2026-10-18**.
All five cumulative stages are loaded and checked. The accepted experiments contain
150 Task 3 observations, 180 new indexed observations and 30 new unindexed controls.

| Resource | Purpose |
|---|---|
| [Loading guide](loading/README.md) | Input contracts, SQL generation, atomic COPY and validation |
| [Loading generator](loading/prepare_load.py) | Verify CSV provenance/headers and generate one atomic stage load |
| [Index experiment database](loading/create_index_database.sql) | Copy the largest clean stage into a dedicated experiment database |
| [Benchmark guide](benchmark/README.md) | Timing protocol, environment, execution and failure handling |
| [Baseline runner](benchmark/run_baseline.py) | Five stages × six queries × five recorded runs |
| [Index runner](benchmark/run_indexes.py) | Five indexes individually, then all together; separate control |
| [Five-stage manifest](manifests/stages.json) | Sources, row counts, hashes, database mappings and measured database sizes |
| [Query review](evidence/query_review.json) | Six-query execution, Q2 row conservation and Q5 subset checks at every stage |
| [Task 3 raw CSV](benchmark/results/task3_baseline_01/task3_raw.csv) | 150 original baseline observations |
| [Task 4 comparison CSV](benchmark/results/task4_indexes_02/task4_raw.csv) | 30 original size-5 baseline rows + 180 new indexed observations |
| [Task 4 control CSV](benchmark/results/task4_indexes_02/control_raw.csv) | 30 additional unindexed observations, kept separate |

## Run the project step by step

Run every command below from the **repository root**: the folder containing `db`, `src` and `ops`.
You need Python 3.10+, PostgreSQL 15+ and a running PostgreSQL server. The accepted experiments used
PostgreSQL 17.11. These examples use `localhost`, port `5432` and user `postgres`; change them if
your database uses different connection details. Enter your password when prompted.

First check that Python and the PostgreSQL command-line client are available:

```sh
python --version
psql --version
```

If `psql` is not found, add your PostgreSQL installation's `bin` folder to PATH and reopen the
terminal. The benchmark scripts can also take `--psql "path/to/psql"` (or `psql.exe` on Windows).
No command below depends on a particular drive letter or local installation directory.

### 1. Prepare the original data

Download the complete five-file ZIP from the [frozen HDB snapshot guide](../data/snapshots/README.md).
For example, if you saved the ZIP in the folder immediately above the repository, extract it with:

```sh
python -m zipfile -e ../hdb-raw-2026-10-18.zip .
python -m pip install -r src/etl/hdb/requirements-download.txt
python src/etl/hdb/download.py
```

**Success:** five `Reused frozen snapshot` messages.

For spatial inputs, download `hawker_geo.csv` from NTULearn or obtain the same original file
from Chen. Place it at `data/raw/spatial/hawker_geo.csv` without editing or re-saving it. Then run:

```sh
python src/etl/spatial/download.py
```

**Success:** all three spatial inputs are downloaded or verified. See the
[spatial guide](../src/etl/spatial/README.md) for source details.

### 2. Generate and verify the first stage

Start with the smallest HDB source, `2015_2016`:

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --stage stage1_2015_2016 --output data/processed/hdb/stage1_2015_2016
python src/etl/hdb/verify.py --stage-dir data/processed/hdb/stage1_2015_2016 --report .hdb-qa/stage1_hdb_validation.json
python src/etl/spatial/pipeline.py --hdb-stage data/processed/hdb/stage1_2015_2016 --output data/processed/spatial/stage1_2015_2016 --stage stage1_2015_2016
python src/etl/spatial/verify.py --stage-dir data/processed/spatial/stage1_2015_2016 --hdb-stage data/processed/hdb/stage1_2015_2016 --report .hdb-qa/stage1_spatial_validation.json
```

**Success:** both verifiers show `passed`; the HDB stage contains **37,153 transactions**.
If these stage folders already exist, verify the existing outputs instead of running the
pipelines again. The pipelines intentionally refuse to overwrite a stage.

### 3. Create and load the first database

Create an empty database using the team's frozen schema:

```sh
psql -X -h localhost -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -v database_name=sd6105_housing -f db/schema/create_database.sql
```

Generate a load script, then execute it against that database:

```sh
python ops/loading/prepare_load.py --hdb-stage data/processed/hdb/stage1_2015_2016 --spatial-stage data/processed/spatial/stage1_2015_2016 --output .hdb-qa/stage1_import.sql
psql -X -h localhost -p 5432 -U postgres -d sd6105_housing -v ON_ERROR_STOP=1 -P pager=off -L .hdb-qa/stage1_load.log -f .hdb-qa/stage1_import.sql
```

**Success:** the table counts are printed and the final line is `COMMIT`. All six tables are
loaded and checked together; an error rolls back the import. The load script automatically uses
Chen's coordinate-enriched building CSV. Creating a load script alone does not import any data.

Now check the six queries:

```sh
psql -X -h localhost -p 5432 -U postgres -d sd6105_housing -v ON_ERROR_STOP=1 -P pager=off -L .hdb-qa/stage1_queries.log -f sql/queries/all_queries.sql
```

**Success:** six result sets are printed without errors. Stage 1's Q5 should select 9 of 26 towns.
This execution checks results; it is not part of the formal timing measurements.

### 4. Repeat for stages 2–5

Each stage contains **all previous sources plus one more file**. Keep a separate database for each.

| Stage | Source to add | Output folder name | Database name | Total transactions |
|---|---|---|---|---:|
| 1 | `2015_2016` | `stage1_2015_2016` | `sd6105_housing` | 37,153 |
| 2 | `2012_03_2014` | `stage2` | `sd6105_stage2` | 89,356 |
| 3 | `2017_onwards` | `stage3` | `sd6105_stage3` | 332,311 |
| 4 | `1990_1999` | `stage4` | `sd6105_stage4` | 619,507 |
| 5 | `2000_2012_02` | `stage5` | `sd6105_stage5` | 989,158 |

For example, the stage-2 HDB build includes **both** source files:

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --source 2012_03_2014 --stage stage2 --output data/processed/hdb/stage2
```

For each later stage, repeat the verification, spatial processing, database creation, loading and
query checks from steps 2–3. Replace the stage folder, database name and log filenames with those
for the current stage. Pass every cumulative source using another `--source` argument.

**Before timing:** all five imports must end in `COMMIT`, and Q5 must return some but not all
towns at every stage. The accepted Q5 town counts are **9, 11, 20, 4 and 2**, respectively.
These folder/database names match [the benchmark configuration](benchmark/stages.json); update
that configuration if you deliberately choose different names. Use a new import-script filename
if one already exists; do not overwrite data or remove a database just to rerun an example.

### 5. Measure the Task 3 baseline

With all five databases ready, choose a **new** experiment output folder:

```sh
python ops/benchmark/run_baseline.py --out ops/benchmark/results/my_task3_run
```

The defaults are `localhost:5432`, user `postgres`. For a different connection, for example:

```sh
python ops/benchmark/run_baseline.py --host localhost --port 5433 --user my_db_user --out ops/benchmark/results/my_task3_run_02
```

**Success:** `COMPLETE: 150 measurements`. The first example writes its raw timings to
`ops/benchmark/results/my_task3_run/task3_raw.csv`. The program sets the timing parameters and
rejects extra indexes. Keep the computer idle during measurements.

### 6. Measure the Task 4 indexes

After accepting the full baseline, copy the largest database for index experiments:

```sh
psql -X -h localhost -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -f ops/loading/create_index_database.sql
```

**Success:** the new database is `sd6105_stage5_indexed`, containing **989,158 transactions**.
Close other connections to `sd6105_stage5` before copying it.

Run the index experiment using the baseline folder created in step 5:

```sh
python ops/benchmark/run_indexes.py --baseline ops/benchmark/results/my_task3_run --out ops/benchmark/results/my_task4_run
```

**Success:** `COMPLETE: 180 indexed measurements + 30 control measurements`. The comparison file
is `ops/benchmark/results/my_task4_run/task4_raw.csv`; the independent control is `control_raw.csv`
in the same folder. Use the same connection options as step 5 if your host, port or user differs.
Do not change the SQL, schema or server settings between the two experiments.

### 7. Check the outputs

After both experiments finish, check the files in your new output folders. The row counts below
exclude the CSV header:

| Experiment folder | File | Expected data rows |
|---|---|---:|
| `my_task3_run` | `task3_raw.csv` | 150 |
| `my_task4_run` | `task4_raw.csv` | 210 |
| `my_task4_run` | `control_raw.csv` | 30 |

The 210 Task 4 comparison rows contain **30 reused Task 3 baseline rows + 180 new indexed rows**.
The 30 independent control observations are stored separately; do not count the reused baseline
rows as new measurements.

Open `manifest.json` in each experiment folder and confirm:

- Both experiments have `status: complete`.
- Task 3 has `measurement_count: 150`.
- Task 4 has `indexed_measurement_count: 180`, `control_measurement_count: 30` and
  `query_results_equal: true`.

Keep the manifests, frozen SQL, metadata and execution plans alongside the CSV files so the
measurements can be checked later.

For detailed timing rules and recovery options, see the [benchmark guide](benchmark/README.md).

## Checks and packaging

```powershell
python -m unittest discover -s ops/benchmark/tests -v
```

Seven tests cover incomplete-result rejection, changed SQL/output/settings, nested index-plan
inspection, unexpected indexes and protection of baseline databases. Collection also validates
the actual experiment files before marking either accepted run complete.

Generated table CSVs and local PostgreSQL files are not committed. Within this module, retain the
accepted raw timing CSVs, timed plans, metadata, query/index snapshots and experiment manifests.
Verbose duplicate psql logs, generated run SQL and the preparation-only first
Task 4 attempt are excluded from Git but preserved locally. Stage import/query logs are retained
under [evidence](evidence/) because they establish actual loading and query acceptance.
The module's Git attributes preserve experiment outputs and original psql logs byte-for-byte,
so Windows/Linux checkout does not invalidate frozen SQL or measurement CSV hashes.

## Further reading

The [report contribution](report.md) contains the experimental method, findings and an example
plotting command for preparing the final report.
