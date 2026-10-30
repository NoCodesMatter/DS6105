# Database operations and performance measurements — Sun NengKe

Schema contract **1.0.0**, PostgreSQL **17.11**, frozen HDB snapshot **2026-10-18**.
All five cumulative stages are loaded and checked. The accepted experiments contain
150 Task 3 observations, 180 new indexed observations and 30 new unindexed controls.

Start with the [handoff](handoff.md) for team integration and [report contribution](report.md)
for Sun's methods, observations and limitations.

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

## Reproduce

1. Restore the [frozen HDB inputs](../data/snapshots/README.md) and the
   [spatial inputs](../src/etl/spatial/README.md), including the manual NTULearn file.
2. Generate each stage's HDB and spatial outputs using the source lists in the five-stage manifest.
   Run both upstream verifiers. They refuse changed sources or inconsistent outputs.
3. Create an empty database for each stage with the authoritative
   [creation script](../db/schema/create_database.sql). Generate an import with the loading
   generator and execute it with psql. The stage commits only if all six imports, exact counts
   and the shared acceptance checks pass.
4. Run and review Q1–Q6 before timing. The committed query-review evidence contains the observed
   result counts; LI owns semantic correctness. Database names can be adjusted in the benchmark
   stage configuration for another machine.
5. Run the baseline runner into a new directory. Accept only a complete 150-row experiment.
6. Create a separate size-5 copy and run the index runner, pointing `--baseline` to the accepted
   baseline directory if using a different name. Keep the same machine, settings and frozen SQL.
7. Give the accepted raw data, metadata and plans to Lu for plots, final index decisions and report
   integration. The report contribution includes the command for the existing plotting program.

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

Submit this module through the team's feature-branch/PR process. Group handoff messages are
provided as text for the owner to send; this workflow does not send messages to teammates.
