# Modeling decisions and normalization

All choices below are an executable proposal for team review. The PDF delegates proximity
definitions to the team; it does not prescribe these thresholds or entity keys.
Shared-contract review is open, not implied by the implementation.

## D1: flat identity is an observed profile

Prescribed resale fields identify a block, street, flat type, storey range, area,
model and lease year, but no unit number or persistent dwelling identifier. A
flat_id therefore identifies the exact observed combination of those attributes,
not a physical home. Two indistinguishable homes share a profile; a real home
reported with different area or storey bins may have more than one profile.
Transaction identity always remains source dataset + original record ordinal.
This preserves transaction counts without inventing repeat-sales histories.

Building is separated because town, address and building coordinates describe a
building shared by many profiles. Town is the source HDB town, not the planning
area/subzone in the geolocation file. One canonical block+street is assumed to
map to one town per frozen snapshot. Any cross-file contradiction is a blocking
data-quality issue for HE/WU; do not silently pick a town or merge addresses.

Source floor-area and model changes create distinct observations, not updates
that overwrite prior transactions. Q3's phrase “average floor area for 3-Room
flats” admits profile-weighted or transaction-weighted interpretations. Proposed
ranking uses observed profiles once each and clearly states that profiles are not
dwelling counts. LI must review this choice; both variants remain expressible.

## D2: dependencies, 3NF and BCNF (revised in 1.0.0-draft.2; concluded at Gate 0)

The earlier text stated "BCNF" unconditionally. That claim depended on dependencies
that only real HDB data could confirm or refute. This section therefore separates
three kinds of dependency:

- **(S) business semantics:** the dependency follows from what the data means.
- **(C) enforced or assumed by code:** a key or ID rule makes it hold.
- **(V) validated on data:** checked by the probes in `validate_loaded_data.sql` on the
  five-file database (HE, 2026-10-30;
  [evidence](../../src/etl/hdb/evidence/gate0_1_0_0/README.md)). One counterexample
  refutes a dependency. Zero counterexamples make it a validated property of the frozen
  snapshot, not an enforced rule.

| Relation | Dependency | Kind | Status |
|---|---|---|---|
| town | town_name is the only attribute | S | Holds |
| hdb_building | building_id <-> (block, street_name) -> town_name, latitude, longitude | C (UUIDv5 of address; UNIQUE) | Holds by construction. If a real address appears in two towns, the load **fails** rather than silently picking one. |
| hdb_building | (latitude, longitude) -> town_name | S (a point lies in one town); V | **No violation (validated).** `fd_probe_coordinate_pairs_shared_by_buildings` = 0 over the 9,831 geocoded buildings, so each pair identifies one building and the determinant is a key of the geocoded rows. The 193 buildings with NULL coordinates are outside the dependency. Not enforced by a constraint. |
| hdb_flat | flat_id <-> (building_id, flat_type, storey_lower, storey_upper, floor_area_sqm, flat_model, lease_commence_year) | C | Holds by construction |
| hdb_flat | **building_id -> lease_commence_year** | S (HDB leases normally start per block); V | **Refuted.** `fd_probe_buildings_with_multiple_lease_years` = 3: 114 Jurong East St 13 (1981, 1982), 21 Teban Gdns Rd (1978, 2013), 37 Teban Gdns Rd (1966, 1981). Not an FD, so the year stays in the flat profile. |
| resale_transaction | transaction_id <-> (source_dataset, source_row) -> all other attributes | C | Holds by construction |
| resale_transaction | (flat, year of sale_month) -> remaining_lease_months for `estimated_years` | C (derivation formula), cross-relation | Not an FD inside the relation, because reported values do not follow the formula. Consistency is checked by `validate_loaded_data.sql`. |
| hawker_centre | hawker_id <-> (centre_name, address) -> stalls, coordinates | C | Holds. In the frozen NEA snapshot, name alone and address alone are also unique (verified on all 107 rows). Both are then candidate keys, so neither creates a violation. |
| hawker_centre | (latitude, longitude) -> centre | S | Verified on hawker_geo.csv: 129 distinct coordinate pairs |
| building_hawker | (building_id, hawker_id) -> distance_m | S | Holds. The distance is also derived from coordinates in two other relations; `validate_loaded_data.sql` checks it to 0.01 m. |

**Conclusion (Gate 0).** All six relations are in **BCNF, and therefore 3NF**, on the
frozen 1990–2026 snapshot (989,158 transactions, 10,024 buildings, 147,045 flat profiles):

- Under the declared keys and dependencies (S and C rows), every non-trivial determinant
  is a candidate key.
- `building_id -> lease_commence_year` does not hold (3 counterexamples). The year
  correctly stays in `hdb_flat` as part of the profile key. Moving it to `hdb_building`
  would make the load fail for those 3 buildings. No schema change is needed.
- `(latitude, longitude) -> town_name` causes no violation, because no coordinate pair is
  shared by two buildings. This is a validated property of the snapshot, not a UNIQUE
  constraint. A new geocoding run must pass the probe again; a shared pair would be a
  geocoding defect for Chen to fix, not a schema change.

`transactions_before_lease_commencement_year` = 51 (36 from 1990–1999, 15 from
2000–February 2012) is a data-quality finding, not a dependency. All 51 keep their source
attributes with `lease_basis = unknown` and a NULL remaining lease.

`validate_loaded_data.sql` keeps reporting the three probes on every loaded stage. A
nonzero count is reported, never fatal.

Class is a deterministic function of distance, and fresh-market eligibility is a function
of the produce-stall count. Both are **derived** (function and views), not stored, so they
introduce no transitive dependency into base relations. Dataset-wide metadata (source hash,
approval vs registration month) lives in manifests, not in a column repeated on every row.

Decomposition joins are lossless under PK/FK links. Each transaction has exactly one profile,
each profile one building and each building one town. Spatial joins fan out across centres,
so Q4/Q5 must reduce to one row per building **before** joining sales. The views
`nearest_hawker` and `nearest_market_hawker` do this.

## D3: distance matrix and cost

Store building-to-centre Haversine distances using only the prescribed coordinate
sources. This is straight-line geographic access, not walking distance or travel
time. No external routing/geocoding API or PostGIS is introduced.

The inspected hdb.csv has 12,442 buildings; the prescribed NEA list has 107
centres. A complete matrix at those counts is **1,331,294 pairs**, independent of
the transaction count. Two UUIDs plus a float8 are 40 bytes of logical payload
per row (~50.8 MiB); PostgreSQL row, page and PK-index overhead is additional.
A full-size synthetic matrix (12,442 x 107) measured **187 MB** (heap 87 MB +
PK index 100 MB). These are synthetic, single-machine figures, not Task 3 measurements;
Sun/Lu must interpret Q4/Q5 runtimes with this fixed spatial cost in mind.

**View rewrite (1.0.0, from Lu's Task 4 analysis).** The nearest views first pick one
centre per building with `DISTINCT ON` and only then call `proximity_class`. Before, the
STRICT (non-inlinable) function ran on every pair before de-duplication. The rows are
identical. On the same synthetic matrix `SELECT * FROM nearest_hawker` went from about
985 ms to about 640 ms, and to about 140–180 ms with the Task 4 candidate index
`building_hawker(building_id, distance_m, hawker_id)`. Lu measured 1,362 → 459 → 156 ms on
real Stage 1–4 data. The rewrite is part of the frozen schema, so the Task 3 baseline and the
Task 4 runs use the same view definition.
Generate only for buildings actually loaded and centres actually geocoded. Newer
HDB data may include buildings absent from this historical geolocation snapshot.

This explicit cost assessment favors the complete matrix for simplicity and
auditable completeness: it preserves both unrestricted and fresh-market nearest
relationships and permits review of alternative class semantics. A nearest-only
association would require proving that omitted centres cannot affect either
query; it would also prevent broader per-centre analysis. Reassess with Chen/Sun
if real observed-building counts or measured costs justify a different contract.

The matrix stores a reproducible snapshot fact derived across tables. Local DDL
does not assert its completeness or recomputation after coordinate changes; the
read-only `validate_loaded_data.sql` does before publication. No cross-table CHECK masquerades as a
continuously maintained consistency guarantee. See PostgreSQL's [constraint
documentation](https://www.postgresql.org/docs/17/ddl-constraints.html).

## D4: spatial classes and sample weighting

Near [0,500 m), medium [500 m,1000 m), far [1000 m,2000 m]; beyond 2,000 m there is no
proximity level (NULL). Boundaries are mutually exclusive. Every distance up to the 2,000 m
maximum effective distance has exactly one class.

- **500/1000 m:** Chen checked these against real nearest distances and they are kept.
- **2,000 m:** follows the rule in [decision F-03](proposals/F03_proximity_semantics.md):
  the p95 of the nearest fresh-market distance (5.1–5.3 km), capped at 2,000 m.
- **Cost:** about 29% of transactions across the five files have no class. They stay in all
  non-spatial queries.

Q4 uses nearest among all geocoded prescribed centres. Q5 uses nearest among
centres with market_produce_stalls >0. Thus a sale has at most one class per query.
Missing coordinates/eligible centres mean unknown coverage; never classify them
as far, invent a coordinate or discard the transaction from nonspatial queries.
Use ascending stable centre UUID for distance ties. Do not round distances before
classification. Historical transactions linked to static 2016/2022-era amenities
do not prove historical access at sale time or a causal price effect.

## D5: constraints and baseline

Use UUID and explicit natural UNIQUE keys; fixed-point price/area; month markers;
required text and finite numeric domains; paired optional coordinates; constrained
lease basis/value consistency; RESTRICT for parent deletion. No synthetic identity
sequences, silent deletes, mandatory geolocation that loses historical sales,
secondary optimization indexes or extension dependency. PostgreSQL's PK/UNIQUE
indexes remain part of the unoptimized baseline.

Producer-side decimal precision validation is necessary because numeric(p,s)
rounds extra fractional digits during input.

**1.0.0-draft.2.** The contract always said "no zero-coordinate sentinels",
but the DDL accepted (0,0). `building_not_zero_sentinel` and `hawker_not_zero_sentinel`
now reject exactly the (0,0) pair, including -0.0. NULL pairs, ordinary coordinates and
a single zero axis remain valid.

No Singapore bounding box, year range, storey cap, area cap or price floor was added. Those
would be **new** business rules, and no real HDB data is available to show they cannot
reject valid historical rows. Candidate bounds, to be checked against the staged data before any is adopted:

| Candidate bound | Evidence today | How to validate | Owner |
|---|---|---|---|
| `sale_month >= DATE '1990-01-01'` | The prescribed collection starts with the 1990–1999 file | `min(month)` over the five files | HE → WU |
| `lease_commence_year` within observed min/max ± margin | None local | `min/max(lease_commence_date)` | HE → WU |
| `storey_upper` ≤ observed maximum | None local | maximum storey-range upper bound | HE → WU |
| `floor_area_sqm` ≤ observed maximum | None local | `min/max(floor_area_sqm)` | HE → WU |
| `resale_price` ≥ observed minimum | None local | `min(resale_price)` per file | HE → WU |
| Singapore envelope lat [1.15, 1.50], lon [103.5, 104.1] | hdb.csv and hawker_geo.csv both lie inside | Chen's coordinate QA | Chen |
| Sale year ≥ lease commencement year | Cannot be a CHECK (cross-table) | Reported by `transactions_before_lease_commencement_year`: 51 on the five-file database, all with `lease_basis = unknown` | HE |
| `HEADER MATCH` in the loader | PostgreSQL ≥ 15 is already required | — | Sun |

Local checks cannot validate actual
address matches, completeness against raw files or source row provenance. Those
are ETL/loader reconciliation obligations, not guarantees claimed for the DDL.

## Decision log (Gate 0, 2026-10-30)

| Item | Owners | Status |
|---|---|---|
| Observed-profile grain; address -> town assumption; stable serialization | HE, LI | Adopted. HE's pipeline uses them for all five files. |
| Full matrix, thresholds, unrounded boundaries, missing-coverage policy | Chen, Sun, LI | Adopted. Full matrix kept; 500/1000 m confirmed on real distances. |
| Market-produce count -> fresh market, source/geolocation crosswalk | Chen | Adopted. 104 matches approved by Chen (2026-10-23); 3 unmatched. |
| Hawker inventory (25 geo-only centres, 3 NEA centres without coordinates) | Chen, LI, WU | **Decided: Option A** (NEA 107 only). See [F-02](proposals/F02_hawker_coverage.md). |
| Bounded third proximity class / maximum effective distance | Chen, LI, WU | **Decided: Option B, D_max = 2,000 m.** See [F-03](proposals/F03_proximity_semantics.md). |
| building -> lease_commence_year; coordinate uniqueness (BCNF) | HE (data), WU | **Concluded: BCNF.** The lease dependency is refuted (3 buildings); 0 shared coordinate pairs. No schema change. See §D2. |
| Q3 profile weighting; Q4 nearest; Q5 nearest eligible and budget meaning | LI | Adopted in LI's frozen `sql/queries/` (Q3 profile-weighted; Q4 near vs far; Q5 excludes NULL class). The Q5 budget must be checked at every stage. |
| Final building CSV enrichment handoff and six-table load order | HE, Chen, Sun | Working: Stage 1 loaded with Chen's geocoded `hdb_building.csv`. Sun's official loader is pending. |
| Nearest-view rewrite (class computed after `DISTINCT ON`) | Lu, WU | **Adopted in 1.0.0**, before the Task 3 baseline |
| Official timings, source-aware results, schema/index compatibility | Sun, LI, Lu | Future G2-G5 review; do not sign off without evidence |
