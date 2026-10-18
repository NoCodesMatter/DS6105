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

## D2: dependencies, 3NF and BCNF (revised in 1.0.0-draft.2)

The earlier text stated "BCNF" unconditionally. That claim depends on dependencies
that real HDB data has not yet confirmed or refuted. This section therefore separates
three kinds of dependency:

- **(S) business semantics:** the dependency follows from what the data means.
- **(C) enforced or assumed by code:** a key or ID rule makes it hold.
- **(V) Pending Validation:** plausible, but must be confirmed or refuted against the
  five resale files and hdb.csv. None of these are in the repository.

| Relation | Dependency | Kind | Status |
|---|---|---|---|
| town | town_name is the only attribute | S | Holds |
| hdb_building | building_id <-> (block, street_name) -> town_name, latitude, longitude | C (UUIDv5 of address; UNIQUE) | Holds by construction. If a real address appears in two towns, the load **fails** rather than silently picking one. |
| hdb_building | (latitude, longitude) -> town_name | S (a point lies in one town) | **Pending Validation.** Harmless if each coordinate pair identifies one building (it is then a candidate key). Probe: `fd_probe_coordinate_pairs_shared_by_buildings`. |
| hdb_flat | flat_id <-> (building_id, flat_type, storey_lower, storey_upper, floor_area_sqm, flat_model, lease_commence_year) | C | Holds by construction |
| hdb_flat | **building_id -> lease_commence_year** | S (HDB leases normally start per block) | **Pending Validation.** Probe: `fd_probe_buildings_with_multiple_lease_years` |
| resale_transaction | transaction_id <-> (source_dataset, source_row) -> all other attributes | C | Holds by construction |
| resale_transaction | (flat, year of sale_month) -> remaining_lease_months for `estimated_years` | C (derivation formula), cross-relation | Not an FD inside the relation, because reported values do not follow the formula. Consistency is checked by `validate_loaded_data.sql`. |
| hawker_centre | hawker_id <-> (centre_name, address) -> stalls, coordinates | C | Holds. In the frozen NEA snapshot, name alone and address alone are also unique (verified on all 107 rows). Both are then candidate keys, so neither creates a violation. |
| hawker_centre | (latitude, longitude) -> centre | S | Verified on hawker_geo.csv: 129 distinct coordinate pairs |
| building_hawker | (building_id, hawker_id) -> distance_m | S | Holds. The distance is also derived from coordinates in two other relations; `validate_loaded_data.sql` checks it to 0.01 m. |

**What is proved now.** Under the declared keys and dependencies (S and C rows), all six
relations are BCNF and therefore 3NF.

**What depends on validation.** Two cases could change that:

1. **If `building_id -> lease_commence_year` holds** (zero counterexamples in all five
   files), `hdb_flat` is **3NF but not BCNF**.
   - It stays 3NF because `lease_commence_year` belongs to the seven-attribute candidate
     key, which makes it a prime attribute.
   - The BCNF repair would be to move `lease_commence_year` to `hdb_building`. That changes
     the flat key, the flat UUID input and both HE's CSV and Sun's CSV, so it is a team
     decision (HE, LI, Sun).
   - If counterexamples exist, the attribute genuinely varies within a block, and the
     current placement is required.
2. **If two buildings share a coordinate pair**, `(latitude, longitude) -> town_name`
   makes `hdb_building` violate 3NF formally. In practice that means a geocoding defect,
   so Chen should fix the coordinates rather than the schema change.

`validate_loaded_data.sql` now reports both probes on every loaded stage, plus
`transactions_before_lease_commencement_year`. A nonzero count is reported, never fatal.

Until the probes run on real stages, the report must say: **"3NF; BCNF under stated
assumptions (Pending Validation)"**. It must not say "BCNF" unconditionally.

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
PK index 100 MB). The nearest-centre views took about 0.6 s on one laptop. These are
synthetic, single-machine figures, not Task 3 measurements; Sun/Lu must interpret Q4/Q5
runtimes with this fixed spatial cost in mind.
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

Near [0,500 m), medium [500 m,1000 m), far [1000 m,infinity). Boundaries are
mutually exclusive and exhaustive for valid distances. 500/1000 m are simple
interpretable proposed thresholds, not empirically justified cut points yet.
Inspect real class counts and geographic coverage with Chen before freezing them.
The third class has no upper bound. The contract is
**unchanged** pending team review; the alternatives and a recommendation are in
[proposals/F03_proximity_semantics.md](proposals/F03_proximity_semantics.md).

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
| Sale year ≥ lease commencement year | Cannot be a CHECK (cross-table) | Reported by `transactions_before_lease_commencement_year` | HE |
| `HEADER MATCH` in the loader | PostgreSQL ≥ 15 is already required | — | Sun |

Local checks cannot validate actual
address matches, completeness against raw files or source row provenance. Those
are ETL/loader reconciliation obligations, not guarantees claimed for the DDL.

## Decisions awaiting team review

| Item | Reviewer / dependency | Status |
|---|---|---|
| Observed-profile grain; address -> town assumption; stable serialization | HE, LI | Proposal; review real five-file conflicts |
| Full matrix, radius, thresholds, unrounded boundaries, missing-coverage policy | Chen, Sun, LI | Proposal; actual distance distribution unavailable |
| Market-produce count -> fresh market, source/geolocation crosswalk | Chen | Count field verified; 17/87/3 candidates unapproved; see [F-02 proposal](proposals/F02_hawker_coverage.md) |
| Hawker inventory (25 geo-only centres, 3 NEA centres without coordinates) | Chen, LI | Open; options in F-02 proposal |
| Bounded third proximity class / maximum effective distance | Chen, LI | Open; options in [F-03 proposal](proposals/F03_proximity_semantics.md) |
| building -> lease_commence_year (BCNF of hdb_flat) | HE (data), WU | Pending Validation; probe in validate_loaded_data.sql |
| Q3 profile weighting; Q4 nearest; Q5 nearest eligible and budget meaning | LI | Proposed; no final query parameters chosen |
| Final building CSV enrichment handoff and six-table load order | HE, Chen, Sun | Defined interface; module integration absent |
| Official timings, source-aware results, schema/index compatibility | Sun, LI, Lu | Future G2-G5 review; do not sign off without evidence |
