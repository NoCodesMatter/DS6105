# HDB source profiling

Contract: `1.0.0-draft.2`. All source records inspected; no sampling.

Source hashes, URLs and acquisition times are in `data/manifests/hdb_sources.json`.

| Source | Observed months | Records | Lease bases | Fatal records | Equal-looking excess records (preserved) |
|---|---|---:|---|---:|---:|
| 1990_1999 | 1990-01 to 1999-12 | 287,196 | {'estimated_years': 287160, 'unknown': 36} | 0 | 826 |
| 2000_2012_02 | 2000-01 to 2012-02 | 369,651 | {'estimated_years': 369636, 'unknown': 15} | 0 | 513 |
| 2012_03_2014 | 2012-03 to 2014-12 | 52,203 | {'estimated_years': 52203} | 0 | 248 |
| 2015_2016 | 2015-01 to 2016-12 | 37,153 | {'reported_years': 37153} | 0 | 24 |
| 2017_onwards | 2017-01 to 2026-10 | 242,955 | {'reported_months': 242955} | 0 | 318 |

## Cross-file checks

- Distinct canonical addresses: 10,024.
- Addresses assigned to multiple towns: **0**. Any selected stage containing these conflicts must fail until HE/WU agree a correction or contract revision.
- Buildings with multiple lease commencement years: **3**. This is reported evidence, not grounds to remove records.
- Coordinate uniqueness is outside this module; building coordinates are supplied by Chen.

## Interpretation

Older files without a remaining_lease column use the contract's year-resolution estimate. Missing or invalid values in a present remaining_lease column remain unknown and are diagnosed.
Numeric year values and text years/months retain their distinct lease_basis. Storey bins are preserved. Historical MULTI-GENERATION is explicitly mapped to MULTI GENERATION.
Equal-looking rows are counted using complete raw-record SHA-256 signatures, but are never removed: each source record retains its own transaction identity.
All field ranges, source categories, transformations and cross-file counterexamples are in profile.json. Source-level errors and warnings with original row numbers are in source_issues.csv.
The 2017-onwards file is a changing public dataset: reuse the frozen bytes and hash for experiments, not a fresh live download.
