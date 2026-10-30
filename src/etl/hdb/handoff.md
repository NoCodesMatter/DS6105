# HDB ETL: first-stage handoff and report material

The [Task 2 report](report.md) presents the HDB methods, findings and PostgreSQL validation
results in assignment-report form. An [editable Word version](report.docx) is available for
integration into the final group report.

## Gate 0 follow-up on 30 October 2026

The five frozen HDB files and Chen's spatial outputs have been imported into a new PostgreSQL
database using contract 1.0.0. All 989,158 transactions are present, and the complete shared
validator passes. The requested dependency probe counts are **3, 0 and 51** in the order
listed in WU's handover. The [Gate 0 evidence](evidence/gate0_1_0_0/README.md) contains the
three addresses, lease years, coordinate coverage, source breakdown and executable detail queries.
The frozen 2017 onwards file is available in the
[HDB source release](https://github.com/Junde-W/SD6103_PROJECT/releases/tag/hdb-snapshot-2026-10-18).

## Initial HDB implementation and verification on 18 October 2026

The HDB processing module acquires the five prescribed resale datasets, freezes their original
bytes and source metadata, profiles every record, and produces the four HDB-side CSVs under
schema contract 1.0.0-draft.2. The existing schema and shared UUID helpers are unchanged.
The first source file (2015-2016, the smallest file) and a separate all-five-source QA stage have
been processed. PostgreSQL import verification complements CSV structure, key relationships and
complete source-to-output reconciliation; the individual import reports record their results.
All counts and import results below refer to the frozen 2026-10-18 snapshot. Raw/processed CSVs
and the local test database are excluded from Git. Teammates can use the [README](README.md)
to restore the frozen inputs and regenerate outputs; its rerun examples preserve committed evidence.

## Source inspection (2026-10-18 snapshot)

| Source coverage | Records | Remaining-lease representation | Identical-looking excess records, retained |
|---|---:|---|---:|
| 1990-1999 | 287,196 | Column absent; estimate at year resolution | 826 |
| 2000-Feb 2012 | 369,651 | Column absent; estimate at year resolution | 513 |
| Mar 2012-Dec 2014 | 52,203 | Column absent; estimate at year resolution | 248 |
| 2015-2016 | 37,153 | Reported integer years | 24 |
| Jan 2017-Oct 2026 | 242,955 | Reported text years/months | 318 |
| **Total** | **989,158** | | **1,929** |

The first three files contain 10 fields; the last two include `remaining_lease` as an eleventh
field. All five files have zero blank source values and zero fatal normalization errors in this
snapshot. Historical capitalization and the `MULTI-GENERATION` label are normalized explicitly.
Storey intervals differ across time and are preserved rather than made artificially uniform.

## Evidence requiring architectural review

There are **10,024** distinct canonical block/street addresses and **zero** address-to-town
conflicts across all five files. Three addresses have multiple lease commencement years:

| Block | Street | Observed lease years |
|---|---|---|
| 114 | JURONG EAST ST 13 | 1981, 1982 |
| 21 | TEBAN GDNS RD | 1978, 2013 |
| 37 | TEBAN GDNS RD | 1966, 1981 |

These are counterexamples to a universally assumed building-to-lease-year dependency in the
raw snapshot. They are not, by themselves, proof that either source value is erroneous or that
one value should replace another. Source row witnesses are recorded in `evidence/profile.json`.
WU should review the evidence before updating the normalization discussion. The ETL keeps the
source year in the profile identity exactly as required by the existing contract.

**51 transactions** have a sale year before the reported lease commencement year (36 in the
1990s source, 15 in the 2000-Feb 2012 source). The historical estimate would exceed 99 years,
so these transactions retain `remaining_lease_months=NULL` and `lease_basis=unknown`.
Each has two diagnostic events: out-of-range estimate and pre-commencement transaction.
There are therefore 102 warning rows for 51 source transactions, not 102 affected transactions.
No source record is deleted, its date changed or its lease clamped to hide the anomaly.
See `evidence/source_issues.csv` for exact original record positions and values.

## Completed first-stage outputs

For dataset `d_ea9ed51da2787afaf8e51f827c304208`, the output contains 26 towns, 7,921 buildings,
28,725 observed flat profiles and all 37,153 transactions. All leases are reported whole-year
values. There are no warnings or fatal record errors in this source. Five historical
`MULTI-GENERATION` labels were mapped to `MULTI GENERATION`; all text/decimal conversions are
counted in the stage manifest. The 24 equal-looking excess records remain distinct source-row
transactions. No repeat-sale claim about an individual dwelling is inferred from a flat ID.

The saved CSVs pass source/output row reconciliation, unique key and foreign-key checks,
domain/precision checks and ID recomputation. A second build produces identical hashes for
all four CSVs and the diagnostics file. The timestamp and stage label in each run manifest
are intentionally different. Regression tests also exercise all three lease formats, invalid
data, source-file changes and failure behavior; see `evidence/reproducibility.json` and the tests.

## Next integration steps and limitations

1. Chen enriches the building CSV with coordinates, retaining the same address and IDs, then
   prepares hawker and distance-pair data. This stage deliberately supplies NULL coordinate pairs.
2. Sun bulk-loads the tables in dependency order, reconciles counts, and validates the integrated
   six-table stage. Actual import of the four HDB tables has now been exercised in independent
   PostgreSQL test databases using the unchanged schema. This establishes HDB compatibility;
   it does not complete the hawker/spatial integration or replace Sun's final loader.
3. WU reviews the dependency evidence above; LI documents estimated/unknown-lease treatment in Q2.
4. Extend the selected source list for subsequent cumulative stages. All files were fully
   profiled. Stage 1 is the delivered first stage; a separate three-source integration check
   also passed for all 332,311 transactions from Mar 2012-Dec 2014, 2015-2016 and 2017 onwards.
   Its 9,827 buildings and 116,466 profiles passed key and source-reconciliation checks, and all
   three lease representations were exercised. A later PostgreSQL QA run uses all five files:
   27 towns, 10,024 buildings, 147,045 observed flat profiles and 989,158 transactions. This also
   covers the 51 unknown leases in historical data. The five-stage benchmark series remains pending.

## PostgreSQL verification method

`postgres_verify.py` creates a new database and applies the original `001_schema.sql`, preserving
all constraints. It verifies CSV/source provenance before creating the database, imports four tables in one
transaction, and checks table/source counts, key relationships, lease rules and SQL NULLs.
Every field is exported back and compared to its CSV value by primary key; this detects any
numeric rounding or date/text changes, not merely row loss. PostgreSQL 15.19 was used locally.

Thirteen deliberately invalid changes exercise actual SQLSTATE rejection for duplicate keys,
foreign keys, invalid calendar/month dates, price constraints and overflow, NULL required values,
lease range/basis/precision, source ordinals, coordinate pairing and canonical text. These probes
roll back. A separate invalid final-table COPY proves that prior dimension loads also roll back.
Successful import is committed before later checks, and test databases are retained for inspection.
This is a verification tool for isolated databases, not a replacement for the integrated loader.

Temporary SQLite comparison connections are explicitly closed for Windows cleanup. No HDB data
or shared schema changes were required. The PostgreSQL verification run included 53 passing
unit tests, including 13 runner regressions. See `evidence/postgres_stage1_validation.json` and
`evidence/postgres_all_five_validation.json` for actual import evidence and full-value comparisons.
Both actual imports passed. The 51 historical unknown leases were preserved as SQL NULL, all SQL
integrity checks returned zero violations, and all CSV fields matched their database roundtrip.
The shared six-table validator was also executed and correctly rejected the HDB-only database
because geocoded hawkers are absent. `evidence/postgres_validation_summary.json` records that
scope boundary, the runtime provenance and confirmed test-server shutdown.

## Review improvements

The implementation review fixed a cross-platform handoff failure: source-code provenance now
normalizes UTF-8 line endings before hashing, while raw input and CSV hashes remain byte-exact.
Profiling failures preserve previous evidence, and an external snapshot root uses its own default
report destination. NUL characters are rejected before producing PostgreSQL-bound text; none were
present in the five real sources. The downloader validates frozen manifests, attempts recovery of
missing locked objects, retries temporary HTTP/transport failures, and cleans partial downloads.
Source and output record counts remain unchanged. `evidence/review_validation.json` records
the earlier 40-test review before the PostgreSQL runner was added;
`evidence/postgres_validation_summary.json` records the later 53-test suite and actual imports.
See `evidence/review_three_source_validation.json` for the three-source integration result.

The 2017-onwards source changes over time. All experimental stages must reuse the same frozen
source bytes and manifest; a new snapshot requires a full rebuild. The initial validation used
draft contract 1.0.0-draft.2; the Gate 0 check above uses frozen contract 1.0.0.
AI-assisted coding and documentation were used and should be declared
in the final team report according to the course requirements.
