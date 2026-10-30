# Gate 0 dependency probe results

The five frozen HDB sources were loaded with Chen's spatial outputs into a new PostgreSQL
15.19 database on 30 October 2026. The database uses schema contract **1.0.0** from main commit
`057bc73`. All 989,158 transactions from the 18 October snapshot are present.
The complete `db/schema/validate_loaded_data.sql` script passed.

## Results for the normal form discussion

| Probe from the shared validation script | Count |
|---|---:|
| `fd_probe_buildings_with_multiple_lease_years` | **3** |
| `fd_probe_coordinate_pairs_shared_by_buildings` | **0** |
| `transactions_before_lease_commencement_year` | **51** |

The three buildings with multiple lease commencement years are:

| Block | Street | Lease commencement years |
|---|---|---|
| 114 | JURONG EAST ST 13 | 1981, 1982 |
| 21 | TEBAN GDNS RD | 1978, 2013 |
| 37 | TEBAN GDNS RD | 1966, 1981 |

These are counterexamples to `building_id -> lease_commence_year` in the loaded data. Keeping
the year in the flat profile preserves the observed values for each building.

The coordinate probe examines the **9,831 buildings with coordinates** supplied by Chen's
pipeline. Each non-NULL latitude/longitude pair identifies one building in this snapshot.
The other 193 buildings retain NULL coordinate pairs and are excluded by the probe's
`WHERE latitude IS NOT NULL` condition.

Of the 51 transactions whose sale year precedes the lease commencement year, 36 come from
the 1990–1999 source and 15 from the 2000–February 2012 source. All 51 retain their original
transaction attributes, with `lease_basis=unknown` and `remaining_lease_months=NULL`.

## Population and checks

| Table | Loaded rows |
|---|---:|
| `town` | 27 |
| `hdb_building` | 10,024 |
| `hdb_flat` | 147,045 |
| `resale_transaction` | 989,158 |
| `hawker_centre` | 107 |
| `building_hawker` | 1,022,424 |

The HDB stage supplies `town`, `hdb_flat` and `resale_transaction`. Chen's spatial stage
supplies the geocoded `hdb_building`, `hawker_centre` and `building_hawker`. All six CSVs were
imported with explicit column lists and `HEADER MATCH`, in the shared load order, within one
transaction. The 9,831 geocoded buildings and 104 geocoded centres form the complete
1,022,424-row distance matrix.

The HDB verifier reconciled every source record, ID and key relationship. The spatial verifier
checked the complete matrix and all distances; its maximum difference from the independent
Haversine calculation was 2.73e-11 m. The shared SQL validator subsequently passed on the
populated database. Additional boundary checks confirmed that 2,000 m is `far` and distances
above 2,000 m receive NULL under contract 1.0.0.

Rebuilding the HDB stage with contract 1.0.0 produced the same SHA-256 hashes for all four HDB
CSVs as the previous full-snapshot output. The frozen inputs remain available in the
[HDB source release](https://github.com/Junde-W/SD6103_PROJECT/releases/tag/hdb-snapshot-2026-10-18),
including the 242,955-row 2017 onwards file.

## Evidence and reproduction

- [PostgreSQL results and provenance](postgres_probes.json): probe counts, building IDs and
  lease years, source counts, coordinate coverage, CSV hashes and DDL/validator hashes.
- [Shared validator output](validate_loaded_data.txt): the complete output from
  `db/schema/validate_loaded_data.sql`.
- [HDB CSV validation](hdb_validation.json) and [spatial CSV validation](spatial_validation.json).
- [Supporting SQL](probe_details.sql): read-only queries for the counterexamples, coverage,
  source counts and proximity boundaries.

The validated local stages are `data/processed/hdb/gate0_all_five` and
`data/processed/spatial/gate0_all_five`. They were generated with the existing
[HDB pipeline](../../README.md) and [spatial pipeline](../../../spatial/README.md), selecting
all five HDB sources. The raw and processed CSVs can be regenerated from their frozen inputs.

After loading all six tables into a new database using the 1.0.0 DDL, run from the repository root:

```sh
psql -X -v ON_ERROR_STOP=1 --csv -d your_database -f db/schema/validate_loaded_data.sql
psql -X -v ON_ERROR_STOP=1 -A -t -d your_database -f src/etl/hdb/evidence/gate0_1_0_0/probe_details.sql
```

These checks are run after population and outside the Task 3 and Task 4 timing measurements.
