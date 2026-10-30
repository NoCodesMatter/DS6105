# Database loading — Sun NengKe

Python 3.10+ (standard library) and PostgreSQL/psql 15+. Run commands from the repository root.
Use the frozen [schema contract](../../docs/architecture/schema_contract.md) 1.0.0.

## Inputs and preparation

Start with a new database created by [create_database.sql](../../db/schema/create_database.sql).
Run the upstream HDB and spatial verifiers on the selected stage first. Then generate the import:

```sh
python ops/loading/prepare_load.py --hdb-stage data/processed/hdb/stage1_2015_2016 --spatial-stage data/processed/spatial/stage1_2015_2016 --output .hdb-qa/stage1_load.sql
```

The generator checks contract versions, readiness, the spatial-to-HDB manifest link,
and all six imported CSV hashes/headers. It refuses to overwrite an existing SQL file.
Generated SQL contains absolute paths: regenerate after moving data to a different machine.
It does not itself connect to PostgreSQL or import records.

## Import

```sh
psql -X -h localhost -p 5432 -U postgres -d sd6105_housing -v ON_ERROR_STOP=1 -f .hdb-qa/stage1_load.sql
```

These examples assume `psql` is on PATH. Change the host, port or user to match your server.
Passwords are entered in psql, never in scripts or Git. A complete worked example, including
database creation, is in the [step-by-step guide](../README.md#3-create-and-load-the-first-database).

The import locks and requires all six tables to be empty, then bulk-loads in FK-safe order:
town, hdb_building, hdb_flat, resale_transaction, hawker_centre, building_hawker.
Town/flat/transaction CSVs come from the HDB stage; building/hawker/distance CSVs come from
the spatial stage. Explicit column lists, `HEADER MATCH`, UTF-8 and empty-field NULLs are used.

All imports, exact per-table count checks and the unchanged acceptance checks from
[validate_loaded_data.sql](../../db/schema/validate_loaded_data.sql) run in one transaction.
Its standalone transaction wrapper is removed only in the generated SQL; the authoritative
validator is not edited. Any SQL error stops psql and rolls back the import on disconnect.
Success shows six table counts and a final `COMMIT`. `ANALYZE` prepares planner statistics
before commit and is outside all timed experiments. No optional indexes are created.

## Repeat and later stages

Use a new empty database for each cumulative stage, regenerate its CSVs with the upstream
pipelines, run both verifiers and generate a new import file. No reset, deletion, incremental
merge or silent duplicate skipping is performed. Fix ETL defects through the owning module.

The first stage should contain 26 towns, 7,921 buildings, 28,725 profiles, 37,153 transactions,
107 hawker centres and 821,912 distance pairs. Missing coordinates are reported by the shared
validator; they are not automatically treated as import failures.

## Validation status and limitations

The generator was exercised on the actual CSVs/manifests of all five stages; all five actual
PostgreSQL imports ended in `COMMIT` with the exact expected counts and shared acceptance checks.
Generating SQL alone is not an import.
Run the standalone shared validator again whenever the loaded data are changed.
The generated file is a local artifact under ignored `.hdb-qa/`. Accepted benchmark measurements,
environment information and five-stage manifests are linked from the [operations entry point](../README.md).

## Task 4 database copy

After all 150 baseline observations pass collection, use [create_index_database.sql](create_index_database.sql)
to copy the clean largest-stage database to `sd6105_stage5_indexed`. Run it with psql against
`postgres`. It checks the source transaction count and absence of optional indexes before copying.
All other connections to the source database must be closed while PostgreSQL copies its template.
It fails if the destination exists; it never deletes or resets the baseline or an earlier experiment.
