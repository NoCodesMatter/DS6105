# Schema / data contract

**Version: 1.0.0-draft.2. Status: executable proposal; not a team-approved freeze.**

### Change log

| Version | Change | Compatibility |
|---|---|---|
| 1.0.0-draft.2 (2026-10-18) | DDL now **enforces** the existing rule "no zero-coordinate sentinels". New CHECKs `building_not_zero_sentinel` and `hawker_not_zero_sentinel` reject the (0,0) pair. `validate_loaded_data.sql` adds three reported, never-fatal dependency probes. A conceptual ER model ([conceptual_er.png](conceptual_er.png), editable [conceptual_er.drawio](conceptual_er.drawio)) is added. | No table, column, CSV header, key, UUID serialisation or proximity rule changed. Any CSV valid under draft.1 that obeyed the written contract is still valid. UUIDs are unchanged: the UUID namespace is versionless. |
| 1.0.0-draft.1 (2026-10-15) | Initial executable proposal | — |

Open proposals that are **not** part of this contract:
- [F-02 hawker coverage](proposals/F02_hawker_coverage.md)
- [F-03 proximity semantics](proposals/F03_proximity_semantics.md)
Owner: WU JUDNE. Runtime: PostgreSQL 15+ (developed on PostgreSQL 17.4),
Python 3.10+ for shared ID helpers and verification. Namespace: `housing`.
Authoritative definitions: `db/schema/001_schema.sql` and `db/schema/contract.py`.
Changes to names, grain, keys, boundaries, CSV columns or ID serialization require
a version change and affected-owner review before reuse of old outputs.

## Grain, keys and relations

| Base table / CSV filename | Grain | Primary key | Alternate key / foreign keys |
|---|---|---|---|
| town / town.csv | Canonical source HDB town | town_name | None |
| hdb_building / hdb_building.csv | Source block + street address at frozen snapshot | building_id | UNIQUE(block,street_name); town_name -> town |
| hdb_flat / hdb_flat.csv | Observed flat **profile**, not a dwelling | flat_id | UNIQUE(building_id,flat_type,storey_lower,storey_upper,floor_area_sqm,flat_model,lease_commence_year); building_id -> hdb_building |
| resale_transaction / resale_transaction.csv | One original HDB CSV data record | transaction_id | UNIQUE(source_dataset,source_row); flat_id -> hdb_flat |
| hawker_centre / hawker_centre.csv | One prescribed NEA centre at frozen snapshot | hawker_id | UNIQUE(centre_name,address) |
| building_hawker / building_hawker.csv | One geocoded building / geocoded prescribed centre pair | (building_id,hawker_id) | Both components FK to their entities |

All foreign keys restrict deletion and use PostgreSQL's default NO ACTION on
updates. Correct IDs by rebuilding reviewed outputs, not by cascading key edits.
Profiles with the same attributes may stand for multiple units. Never claim to
identify an individual dwelling or infer repeat sales from a profile ID.

## Exact CSV headers, types and null rules

Each following code line is the complete header in import order. All columns are
NOT NULL except explicitly marked optional. Use explicit COPY column lists.

```csv
town_name
```

`town_name`: canonical text, PK.

```csv
building_id,town_name,block,street_name,latitude,longitude
```

`building_id`: UUID; `town_name`: canonical text FK; `block` and `street_name`:
canonical text (retain block letter suffixes and source abbreviations).
`latitude`, `longitude`: optional float8 pair, decimal WGS84 degrees; latitude
[-90,90], longitude [-180,180]. Both null or both present. No zero-coordinate
sentinels: (0,0) is rejected by CHECK since draft.2. Unknown location is an empty
(NULL) pair. Global numeric bounds do not prove a Singapore match; Chen must review
geographic plausibility and outliers.

```csv
flat_id,building_id,flat_type,storey_lower,storey_upper,floor_area_sqm,flat_model,lease_commence_year
```

`flat_id`, `building_id`: UUID. `flat_type`: one of `1 ROOM`, `2 ROOM`, `3 ROOM`,
`4 ROOM`, `5 ROOM`, `EXECUTIVE`, `MULTI GENERATION`. HE maps historical
`MULTI-GENERATION` to `MULTI GENERATION` explicitly and logs that conversion.
Unknown labels require review, never default to a valid label.
`storey_lower`, `storey_upper`: positive smallint bounds, inclusive, upper >= lower;
preserve the source bin rather than inventing an exact floor or harmonizing bins.
`floor_area_sqm`: positive finite numeric(8,2), square metres. `flat_model`:
canonical text. `lease_commence_year`: smallint [1,9999], source year.
Do not equate `year_completed` in hdb.csv with lease commencement.

```csv
transaction_id,flat_id,sale_month,resale_price,remaining_lease_months,lease_basis,source_dataset,source_row
```

`transaction_id`, `flat_id`: UUID. `sale_month`: date `YYYY-MM-01`, source month
as a month marker; not an invented day of actual sale. Approval before March
2012, registration thereafter; the difference is a source limitation.
`resale_price`: positive finite numeric(14,2), SGD. `remaining_lease_months`:
optional smallint [0,1188]. `lease_basis`: required text:

| Basis | Value rule | Interpretation |
|---|---|---|
| reported_months | Non-null integer | Source `Y years M months` -> 12Y+M; missing month suffix means 0 months only if parser validates that source syntax. |
| reported_years | Non-null multiple of 12 | Whole-year source -> 12Y. The original precision remains whole years. |
| estimated_years | Non-null multiple of 12 | Missing historical lease -> 12*(99-(sale year-lease commence year)), using year resolution. Explicit modeling assumption, not a source observation. |
| unknown | NULL only | Unresolved/missing/invalid lease; retain sale, explain diagnostics and Q2 treatment. |

Do not round year-resolution values into claimed exact month precision, use today's
date, clamp negative estimates to zero, or silently change implausible records.
For estimates outside [0,1188], retain `unknown` and report the source anomaly for
review. LI must state estimated/unknown coverage, include an unknown Q2 bucket
or explicitly justify another treatment, and check sensitivity by lease basis.

`source_dataset`: exact data.gov.sg `d_` plus 32 lowercase hexadecimal digits.
`source_row`: positive 1-based CSV **data-record ordinal**, excluding header,
assigned before filtering; quoted multiline fields count as one record. Keep
immutable source file hashes and snapshot timestamps in HE/Sun's sidecar manifest.
No natural uniqueness on prices, months or flat attributes: identical-looking
transactions are preserved. Reprocessing the same source row is a duplicate key.

```csv
hawker_id,centre_name,address,market_produce_stalls,latitude,longitude
```

UUID; canonical source NEA centre name and address; nonnegative integer market
produce stall count from **no_of_mkt_produce_stalls**; optional paired coordinates
with the same rules as building coordinates. `market_produce_stalls > 0` defines
fresh-market eligibility; neither centre type nor name is a substitute. Unknown
stall count must be diagnosed and resolved, never defaulted to zero. Coordinates
must come from the provided **NTULearn hawker_geo.csv**, with reviewed name/address
crosswalks. Retain unmatched centres with null coordinates and coverage diagnostics.

### Real hawker_geo.csv mapping clarification (2026-10-15)

The supplied raw file has **129 records** and the exact source header
`longitude,latitude,NAME,ADDRESS_MYENV`. It is an enrichment source, not the
six-column `hawker_centre.csv` interchange file above. Its longitude/latitude
map by **name**, retaining decimal-degree precision; the raw order is longitude
first, whereas the schema/export order is latitude then longitude. There is no
source centre ID, stall-count field, geometry payload or explicit CRS metadata.
The observed geographic numbers are consistent with the brief's interpretation;
Chen must preserve original GeoJSON provenance.

Use NEA `name_of_centre` and `location_of_centre` for canonical `centre_name`,
`address` and UUID input, and NEA `no_of_mkt_produce_stalls` for eligibility. Raw
`NAME`/`ADDRESS_MYENV` are matching evidence and must not overwrite those key
inputs. **17 raw addresses are blank**; that does not make the NEA entity address
nullable. Retain unmatched NEA entities with both coordinates NULL, not an
invented address/zero coordinate or zero stall count. Do not add geo-only centres
without authoritative attributes and an approved inventory decision.

The frozen 107-entity NEA reference yields 17 exact name/postcode matches,
87 postcode-only candidates and three unresolved centres. These are unapproved
diagnostic candidates; postcode overlap is not proof of identity or historical
location. Extract all six-digit tokens from compound postcodes, normalize NBSP
for matching, hold ambiguous/conflicting/multiple-claim matches, and let Chen
review the final crosswalk. Preserve source hashes and row ordinals in evidence,
not in permanent entity keys. Candidates: [verification/hawker_geo_validation_results.crosswalk.csv](verification/hawker_geo_validation_results.crosswalk.csv) (all unapproved).

**Contract Change: none.** Version, table/CSV structure, identity serialization,
constraints and proximity definitions remain unchanged. This is a clarification
of the existing NEA-authoritative enrichment interface, not approval of a new
production matching policy. Any inventory/key/constraint/semantic change still
requires affected-owner approval.

```csv
building_id,hawker_id,distance_m
```

UUID pair; finite float8 nonnegative spherical straight-line distance in metres,
at most 20,015,115. Emit every geocoded loaded-building x geocoded-prescribed-centre
pair exactly once. Retain full precision, with CSV round-trip-safe float formatting;
never round before classifying. Do not emit pairs involving null coordinates.

The full six-column building CSV is a handoff: HE supplies canonical building IDs,
towns and addresses; Chen enriches coordinates **without changing IDs or address
grain**, and emits the final file for Sun. HE still owns corrections to HDB fields.
If the team prefers a separate location table, request a contract revision rather
than creating incompatible exports privately.

## Identity serialization

Use `db/schema/contract.py` helpers, loaded by Python importlib or an agreed module
import. `NAMESPACE = uuid5(uuid.NAMESPACE_URL, 'urn:sd6105:housing:schema:1')`.
UUID names are JSON arrays encoded with `ensure_ascii=False`, separators `(',',':')`:

- building: `["building", canonical block, canonical street]`
- flat: `["flat", canonical building UUID string, canonical flat type, integer lower,
  integer upper, area string with exactly two decimals, canonical model, integer lease year]`
- hawker: `["hawker", canonical centre name, canonical address]`
- transaction: `["transaction", source dataset ID, integer data-record ordinal]`

Text canonicalization: Unicode NFKC, uppercase, strip and collapse whitespace to
single ASCII spaces. Preserve punctuation; do not expand street names or perform
fuzzy entity merging. Dataset IDs are deliberately lowercase. Decimal helpers
reject non-finite and excess-precision values instead of silently rounding them.
PostgreSQL numeric typmods themselves round excess scale, so **the producer must
apply this check before COPY**. Stable IDs do not depend on source file load order,
coordinates, sale price, Python hash randomization, or a growing sorted row number.
Source file row reorder/update requires a documented new snapshot and full rebuild;
never merge two snapshots for one dataset ID in the same stage.

## Spatial semantics and derived views

Straight-line Haversine, mean Earth radius 6,371,008.8 m, WGS84 degrees. Reference
implementation: `housing.haversine_m(lat1,lon1,lat2,lon2)`; clamp the intermediate
Haversine quantity to [0,1] to avoid floating-point endpoint errors. It assumes
valid coordinates; table constraints and Chen's validation check its inputs.

Exactly three classes: **near [0,500)**, **medium [500,1000)**, **far [1000,+infinity)**
within the valid Earth-distance domain. Thus exactly 500 m is medium and exactly
1,000 m is far. Unknown coordinates mean unclassified, never far. These thresholds
are a draft choice, not values required by the brief or validated by real distances.
The far class has no upper bound. A bounded alternative is proposed, not adopted, in
[proposals/F03_proximity_semantics.md](proposals/F03_proximity_semantics.md).

`building_hawker_proximity` derives class per pair. `nearest_hawker` selects one
minimum-distance centre per building for Q4. `nearest_market_hawker` first filters
produce stalls >0, then selects one nearest eligible centre for Q5. Ties use
ascending hawker UUID. These are plain views, **not extra base tables**; no CSV
is needed for them. Zero eligible/geocoded centres means no row, not a fake match.
All flat profiles in one building inherit its relationships. Coordinate changes
require recomputing the distance matrix and rerunning `validate_loaded_data.sql` before publication.

Q4 compares sales in near and far **nearest-centre** classes; it does not compare
the nearest centre against the geographically most distant centre. Q5 groups each
sale by distance to its nearest **fresh-market** centre, which may differ from its
nearest unrestricted centre. This interpretation needs Chen/LI review. The matrix
also retains every other pair, so another justified association interpretation can
be implemented without changing base tables. Any change must define transaction
weighting and freeze semantics before benchmarks.

## CSV interchange and import

UTF-8 without BOM; comma delimiter; header exactly as above; CSV double-quote
escaping; empty **unquoted** field for SQL NULL; no NaN/Inf/`N/A` sentinels; ISO
dates; dot decimal separator, no currency symbols or thousands separators. Empty
strings are not valid canonical data. All six CSVs are generated artifacts,
including town.csv, not manually seeded SQL. Sidecar manifest includes contract
version, input hashes/URLs/snapshot, stages, table counts, output hashes and all
transformation/rejection/unmatched counts.

FK-safe load order: town, hdb_building, hdb_flat, resale_transaction,
hawker_centre, building_hawker. One transaction per stage; fail on errors, validate
counts and integrity, then commit. Sun owns the bulk loader and reset procedure.
Example client-side import (the actual loader must wrap all six imports):

```sql
\copy housing.hdb_building (building_id,town_name,block,street_name,latitude,longitude) FROM 'hdb_building.csv' WITH (FORMAT csv, HEADER true, NULL '')
```

Do not use `ON CONFLICT DO NOTHING` to hide mismatched outputs. For cumulative
stages regenerate stable dimension IDs, load only new source records or rebuild
the stage, and reconcile complete expected counts. Keep the hawker snapshot and
spatial rules fixed throughout baseline and indexed experiments. New buildings
require new matrix rows. No optional indexes are present in this schema; preserve
all PK/UNIQUE indexes for the baseline and for Task 4 comparisons.

## Acceptance boundaries

DDL enforces local domains, keys, nullability and referential links. The read-only
`validate_loaded_data.sql` additionally checks populated data, full spatial-pair
coverage, source-coordinate distance agreement within 0.01 m, eligible hawkers and
estimated-lease formula consistency. Missing-coordinate/unknown-lease counts are
reported for explicit review. Since draft.2 it also reports three dependency probes:
- `fd_probe_buildings_with_multiple_lease_years`;
- `fd_probe_coordinate_pairs_shared_by_buildings`;
- `transactions_before_lease_commencement_year`.

They are evidence for or against the Pending-Validation dependencies in
design_decisions.md D2, never load failures. Passing these checks does **not** establish source
matching correctness, row-count reconciliation, acceptable coverage or final query
correctness. HE/Chen/Sun must supply those source-aware checks and manifests.
