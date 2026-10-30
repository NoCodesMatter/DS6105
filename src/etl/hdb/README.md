# HDB data processing - HE RUOYUN

Transforms the five HDB resale CSVs in [data.gov.sg collection 189](https://data.gov.sg/collections/189/view)
into the four HDB-side CSVs required by the existing schema contract **1.0.0-draft.2**.
The shared schema and ID helper are reused unchanged. Team approval of the contract remains pending.

## First completed stage

The 2015-2016 file is the smallest source and was selected for Task 2's first run.

| Output | Records |
|---|---:|
| `town.csv` | 26 |
| `hdb_building.csv` | 7,921 |
| `hdb_flat.csv` | 28,725 |
| `resale_transaction.csv` | 37,153 |

All 37,153 original transactions are retained, including 24 equal-looking excess records.
All 37,153 leases are source-reported whole years and have `lease_basis=reported_years`.
Coordinates are empty unquoted CSV fields (SQL NULL) in both columns, for Chen to enrich.
The stage is an HDB handoff, not the completed six-table database.

- [All-five-file profile](evidence/profile.md), [full metrics and counterexamples](evidence/profile.json)
- [First-stage validation](evidence/stage1_validation.json)
- [Reproducibility check](evidence/reproducibility.json)
- [Review regression summary](evidence/review_validation.json), [three-source integration check](evidence/review_three_source_validation.json)
- [PostgreSQL first-stage import](evidence/postgres_stage1_validation.json), [all-five-source import](evidence/postgres_all_five_validation.json)
- [PostgreSQL verification summary and remaining integration scope](evidence/postgres_validation_summary.json)
- [Report text and handoff](handoff.md)
- Raw source lock: `data/manifests/hdb_sources.json`
- Local first-stage output: `data/processed/hdb/stage1_2015_2016/`

The evidence above records completed runs on the frozen 2026-10-18 snapshot.
Download the [frozen CSVs from the GitHub Release](https://github.com/Junde-W/SD6103_PROJECT/releases/tag/hdb-snapshot-2026-10-18):
choose the full five-file ZIP, or the `2017_onwards` ZIP to complete an existing snapshot.
The [snapshot guide](../../../data/snapshots/README.md) gives the extraction steps, counts and checksums.
A fresh clone contains the code, source manifest and verification evidence; extract the CSVs and
use the commands below to generate the processed tables.

## Runtime and inputs

Use Python **3.10+**. Profiling, transformation, validation and core tests use the standard library.
The download script and its mocked-network tests need `requests` (`requirements-download.txt`).
Downloader tests are explicitly skipped if that optional dependency is absent.
Run the commands below from the **repository root**. They work in PowerShell and POSIX shells.

```sh
python -m pip install -r src/etl/hdb/requirements-download.txt
python src/etl/hdb/download.py
python src/etl/hdb/profile.py --output .hdb-qa/profile
```

Rerun examples write reports under ignored `.hdb-qa/` so the committed evidence remains intact.
Running `profile.py` without `--output` in the repository writes into `src/etl/hdb/evidence/`;
reserve that default for an intentional evidence update.

The download script uses the official public metadata and download APIs, with rate-limited
requests and bounded retries. It saves original CSV bytes, SHA-256 hashes, source URLs,
metadata and acquisition timestamps. Existing matching files are reused without network calls.
Signed temporary download credentials are not saved in the manifest.
If a locked raw file is missing, the downloader first tries its saved storage object, then the
official API if necessary. Old objects are not guaranteed to remain publicly available; every
restoration must match the frozen hash. Network/stream interruptions and temporary server errors
have bounded retries; interrupted temporary downloads are cleaned up. Invalid manifests are
rejected before acquisition, and restoring a snapshot does not change its original manifest.

**Use the 2026-10-18 snapshot for the group experiments.** The release supplies the exact bytes
listed in `data/manifests/hdb_sources.json`, including the 242,955-row `2017_onwards` file.
Once extracted, `download.py` checks and reuses all five files. For a separately agreed new data
snapshot, use `download.py --root PATH`, profile it and rebuild the dependent stages together.

## Build and verify one file

Choose an output directory that does not already exist:

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --stage stage1_2015_2016 --output data/processed/hdb/stage1_2015_2016
python src/etl/hdb/verify.py --stage-dir data/processed/hdb/stage1_2015_2016 --report .hdb-qa/stage1_validation.json
python -m unittest discover -s src/etl/hdb/tests -v
```

The completed stage exists only in the original local checkout. If it already exists in your
checkout, use a new output such as `data/processed/hdb/stage1_repeat` and pass that directory to
the verifier, with a separate report path such as `.hdb-qa/stage1_repeat_validation.json`.
The pipeline never overwrites an existing stage. Fatal record errors save a sibling `.failed`
directory containing diagnostics and a failure manifest, and publish no import-ready CSVs.
Malformed CSV/header/snapshot errors stop the run immediately with the source error.

Each successful stage contains four table CSVs, `diagnostics.csv` and `manifest.json`.
The manifest records source hashes/timestamps, code hashes, contract version, transformations,
warning counts, source/output reconciliation, table counts and output hashes.
The four CSV byte streams are deterministic for the same code and frozen sources; the run
timestamp and user-supplied stage label in the manifest are intentionally run-specific.
Source-code hashes use `utf8-lf-v1` (LF-normalized UTF-8), so Git's Windows/macOS/Linux line-ending
conversion does not trigger a false code-change error. Actual code changes still fail verification.
Raw source files and generated CSVs retain strict byte-level hashes.

## Cumulative stages

Repeat `--source` to select more files; the label or exact dataset ID is accepted.
Argument order does not affect CSV order or identity. This regenerates a complete stage,
not an incremental append and not five arbitrary chunks of one source file.

| Suggested stage | Sources included | Expected original transactions for this snapshot |
|---|---|---:|
| 1 | `2015_2016` | 37,153 |
| 2 | + `2012_03_2014` | 89,356 |
| 3 | + `2017_onwards` | 332,311 |
| 4 | + `1990_1999` | 619,507 |
| 5 | + `2000_2012_02` | 989,158 |

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --source 2012_03_2014 --stage stage2 --output data/processed/hdb/stage2
```

This stage order is a proposal for Sun to approve, not a course-mandated order.
Stage 1 is the delivered first stage. A separate review integration run combined `2015_2016`,
`2012_03_2014` and `2017_onwards`: all 332,311 transactions, 9,827 buildings and 116,466 profiles
passed verification, exercising all three lease formats. Its CSVs are local QA artifacts under
`.hdb-qa/review_three_source/`, not a complete five-stage benchmark series. All five raw files
were fully profiled. The complete five-file cumulative output was subsequently generated for PostgreSQL
verification under `.hdb-qa/postgres_all_five/`: 27 towns, 10,024 buildings, 147,045 flat profiles
and 989,158 transactions. This QA output does not constitute the five-stage benchmark series.

For a separate snapshot root, pass both `--root PATH` and
`--manifest PATH/data/manifests/hdb_sources.json` to building/verification.
Profiling needs only `--root PATH`: its default manifest and report directory then follow that
snapshot root (`data/manifests/hdb_profile/`) rather than overwriting this repository's evidence.
Use `--output` to choose another profiling destination. Profiling prepares all three reports
before replacing old evidence and rolls back ordinary publication errors. It does not provide
multi-file transaction guarantees for concurrent readers or forced process termination.

## Actual PostgreSQL import verification

Both real imports passed on PostgreSQL **15.19** on 2026-10-18: the 37,153-transaction first stage and the
989,158-transaction all-five-source QA stage. All four tables roundtripped without value changes.
The latter retained all 51 unknown leases as SQL NULL, with zero orphaned keys or count mismatches.
Each database passed 13 constraint rejection probes and the failed-COPY rollback check. The complete
unit regression suite passed 53 tests. The local test server was stopped after verification and its
data retained. See the [summary](evidence/postgres_validation_summary.json).

`postgres_verify.py` validates an HDB handoff in a **new, retained test database** using PostgreSQL
15+ and `psql`. It requires a running server and a role with `CREATEDB`; passwords are supplied
through libpq's password file (`.pgpass` on POSIX or `%APPDATA%/postgresql/pgpass.conf` on Windows),
`PGPASSFILE` or environment, not CLI arguments or evidence files.
Choose a different database name for each run. Existing databases are never reset or dropped.
Use `--psql PATH`, `--host HOST` and `--port PORT` if the defaults do not match your setup.
Install and start PostgreSQL separately before running this command; the runner does not install
or start a server. The example assumes a running local server on port 5432 and an available
`postgres` role. Use your own permitted role where these defaults do not apply.

```sh
python src/etl/hdb/postgres_verify.py --user postgres --database hdb_stage1_check --stage-dir data/processed/hdb/stage1_2015_2016 --report .hdb-qa/postgres_stage1_validation.json
```

The runner first reconciles the CSVs with the frozen original sources, then applies the unchanged
`db/schema/001_schema.sql`. It uses explicit contract columns and a single transaction for the four
CSV imports. A separate deliberate failure in the final COPY proves that all earlier table loads
roll back. Successful import is committed before the following checks; the database is retained
even if a later check fails, so this is an isolated verification tool rather than Sun's final loader.

Checks include row/source counts, keys and relationships, lease formulae, real SQL NULLs, 13 rejected
constraint examples, and **every field of every row** exported back from PostgreSQL and compared
with the input CSVs by primary key. This detects numeric rounding as well as missing/changed values.
Row order and CSV line endings are ignored. A failed attempt replaces any stale success report
with failure evidence. Temporary comparison databases are explicitly closed for Windows cleanup.

The all-five-source QA stage can be built and checked separately (use unused output/database names):

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --source 2012_03_2014 --source 2017_onwards --source 1990_1999 --source 2000_2012_02 --stage postgres_all_five --output .hdb-qa/postgres_all_five
python src/etl/hdb/postgres_verify.py --user postgres --database hdb_all_five_check --stage-dir .hdb-qa/postgres_all_five --report .hdb-qa/postgres_all_five_validation.json
```

The original verification checkout keeps its runtime binaries, local credentials, database files
and QA CSVs under ignored `.hdb-qa/`. These are not distributed in Git. Compact verification
evidence is tracked. The actual local PostgreSQL version and schema,
source and CSV hashes are recorded in the import reports.

## Transformation policy

| Source field | Treatment |
|---|---|
| `town`, `block`, `street_name`, `flat_type`, `flat_model` | Reject NUL characters that PostgreSQL cannot store. Then use existing `contract.canonical_text`: Unicode NFKC, uppercase, trim/collapse whitespace. Preserve punctuation, block suffixes and street abbreviations. No fuzzy merges. |
| `flat_type` | Explicit historical `MULTI-GENERATION` to `MULTI GENERATION` mapping, counted in diagnostics. Unknown categories fail. |
| `month` | Validate `YYYY-MM`; export `YYYY-MM-01` as a month marker. Preserve the approval/registration distinction in source metadata. |
| `storey_range` | Parse and retain the original lower/upper bounds. Do not infer an exact floor or harmonize historical bins. |
| `floor_area_sqm`, `resale_price` | Exact positive two-decimal strings within the SQL numeric domains. Reject nonfinite or excess-precision values; never round to hide an error. |
| `lease_commence_date` | Valid integer year; export `lease_commence_year`. |
| Absent `remaining_lease` column | `12 * (99 - (sale_year - lease_year))`, basis `estimated_years`; out-of-range results remain NULL/unknown and are reported. |
| Numeric remaining lease | Whole years times 12, basis `reported_years`. |
| Text remaining lease | Validated years/months syntax, basis `reported_months`; missing month suffix means zero months only for the accepted years-only text syntax. |
| Invalid/blank value in a present lease column | Keep the transaction, export NULL/unknown and report it. Never silently substitute an estimate. |
| IDs | Import `db/schema/contract.py`; use its UUIDv5 helpers and exact CSV column order. |
| Transaction identity | Dataset ID + original 1-based CSV data-record ordinal, excluding header. Quoted multiline fields count as one record. Equal-looking records remain separate transactions. |
| Building coordinates | Both NULL for Chen's later enrichment. Address and building ID must remain unchanged. |

One address mapping to two towns is a blocking conflict; no town is silently chosen.
Multiple lease commencement years in a building are reported but retained as distinct profiles.

## Checks and handoff boundaries

`verify.py` checks source and output hashes, CSV headers/encoding, required fields, numeric domains,
primary/natural key uniqueness, deterministic IDs, all three HDB foreign-key links, dimension
usage, lease rules, and every original transaction's source ordinal and normalized values.
Unit tests cover expected parsing outcomes, equal-looking records, quoted multiline records,
source changes, partial-stage failures, multiple-town conflicts, lease variants, cumulative
input order, repeatability, existing-output preservation and tampering.
Review regressions also cover source-code newline portability, NUL input, profiling rollback,
external snapshot defaults, frozen-object recovery, manifest validation and download interruptions.

- **Chen:** use the six-column building CSV; fill its coordinates without changing IDs/addresses.
- **Sun:** use the manifest counts and load `town`, `hdb_building`, `hdb_flat`, `resale_transaction`
  in this order, after Chen's building enrichment for the integrated stage. Do not patch CSVs manually.
- **WU:** review the three observed building/lease counterexamples and 51 pre-commencement transactions.
- **Lu:** adapt `handoff.md` for the report, distinguishing actual HDB import verification from full
  hawker/spatial integration and benchmarking.

The shared `validate_loaded_data.sql` also requires hawker/spatial data and is unsuitable as the
acceptance gate for the four-table HDB handoff alone. Running it on the all-five HDB database
correctly failed with `No geocoded hawkers: Q4/Q5 cannot be accepted`; the summary records that
remaining integration requirement. No schema, spatial pipeline, queries, indexes
or benchmarking files were modified.

Frozen raw CSVs are distributed through the linked GitHub Release. Source metadata, code and
compact evidence are versioned in Git; processed stages are generated locally from those inputs.
