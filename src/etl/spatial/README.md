# Hawker and geolocation processing - Chen YuChi

Produces the three spatial CSVs of schema contract **1.0.0-draft.2** for one HDB stage:

| Output | Content |
|---|---|
| `hawker_centre.csv` | The 107 prescribed NEA centres, with coordinates from `hawker_geo.csv` through the reviewed crosswalk |
| `hdb_building.csv` | HE's building handoff with `latitude`/`longitude` filled from `hdb.csv`; IDs, towns and addresses unchanged |
| `building_hawker.csv` | Haversine distance (m) for every geocoded building x geocoded centre pair |

Each stage directory also holds `diagnostics.csv` (every NULL coordinate and review flag, with its
reason) and `manifest.json` (input hashes, counts, output hashes). The proximity classes and the
nearest-centre views are derived in SQL (`housing.proximity_class`, `nearest_hawker`,
`nearest_market_hawker`); this module stores distances only and never rounds them.

## Inputs

| Source | Location | How it is obtained |
|---|---|---|
| NEA list of hawker centres (data.gov.sg `d_68a42f09f350881996d83f9cd73ab02f`, 2016 snapshot) | `data/raw/spatial/d_68a42f09f350881996d83f9cd73ab02f.csv` | `download.py` (public API) |
| `hdb.csv` from [BlueSkyLT/siteselect_sg](https://github.com/BlueSkyLT/siteselect_sg) | `data/raw/spatial/hdb.csv` | `download.py`, pinned to commit `567427f` |
| `hawker_geo.csv` (NTULearn) | `data/raw/spatial/hawker_geo.csv` | **Manual**: download from NTULearn and place it there |
| Reviewed NEA to `hawker_geo` crosswalk | `docs/architecture/verification/hawker_geo_validation_results.crosswalk.csv` | In the repository (see below) |
| HDB stage from `src/etl/hdb` | e.g. `data/processed/hdb/stage1_2015_2016/` | HE's `pipeline.py` |

`data/manifests/spatial_sources.json` freezes the three spatial inputs (SHA-256, size, records,
header). Every run checks the hashes first; a changed file is refused, never silently used.
Raw and processed data stay out of Git (`data/raw/`, `data/processed/` are ignored).
`hdb.csv` comes from Lan et al. (2022), *Remote Sensing* 14(15):3579; its README asks users to cite it.

## Run

Python 3.10+, standard library only. Run from the repository root:

```sh
python src/etl/spatial/download.py
python src/etl/spatial/pipeline.py --hdb-stage data/processed/hdb/stage1_2015_2016 --output data/processed/spatial/stage1_2015_2016 --stage stage1_2015_2016
python src/etl/spatial/verify.py --stage-dir data/processed/spatial/stage1_2015_2016 --hdb-stage data/processed/hdb/stage1_2015_2016
python -m unittest discover -s src/etl/spatial/tests -v
```

`download.py` only verifies files that are already present. The pipeline never overwrites an
existing output directory and publishes all files together. The same inputs give byte-identical
CSVs (checked by the tests and on stage 1); only `created_utc` in the manifest changes.

Figures for the threshold decisions:

```sh
python src/etl/spatial/analysis.py --spatial-stage data/processed/spatial/stage1_2015_2016 --hdb-stage data/processed/hdb/stage1_2015_2016 --output <dir>
```

### Loading (for `ops/`)

Load `town`, `hdb_flat` and `resale_transaction` from the HDB stage, and `hdb_building`,
`hawker_centre` and `building_hawker` from the spatial stage, in contract load order
(`town`, `hdb_building`, `hdb_flat`, `resale_transaction`, `hawker_centre`, `building_hawker`).
The spatial `hdb_building.csv` replaces the HDB stage's file with NULL coordinates. The HDB stage
is not edited in place: HE's `verify.py` checks its files against the hashes in its manifest, and
this stage's `manifest.json` records the hash of that manifest. Empty unquoted fields are SQL NULL.
Then run `db/schema/validate_loaded_data.sql`.

## Transformations and review decisions

**Hawker centres.** Identity, address and `market_produce_stalls` come from the NEA list only
(`contract.hawker_id`, canonical text). A non-integer stall count stops the build; it is never
defaulted to 0. Coordinates come from `hawker_geo.csv` (longitude/latitude swapped into schema
order, full precision) through WU's candidate crosswalk, in which the spatial owner approved the
104 matched rows (`approved_for_production = True`, 2026-10-23):

| `status` | Centres | Evidence |
|---|---:|---|
| `exact_name_and_postcode` | 17 | Identical name and six-digit postcode |
| `postcode_only_review` | 87 | Same postcode and identical block + street text; names differ only in style ("Blk 105 Hougang Ave 1" vs "Hougang Ave 1 Blk 105 (Hougang 105 Hainanese Village Centre)") |
| `unmatched` | 3 | No `hawker_geo` record; coordinates NULL. All three have 0 produce stalls, so Q5 is unaffected |

The three unmatched centres: Market Street Food Centre (Golden Shoe car park; `hawker_geo` only
has the newer Market Street Hawker Centre, a different site), Blk 4A Woodlands Centre Road and
Blks 1A/2A/3A Commonwealth Drive (no record with these postcodes or addresses).
Without coordinates they have no distance rows, so in Q4 a building next to one of them is
classed by its next-nearest centre. For Blks 1A/2A/3A Commonwealth Drive (Tanglin Halt Food
Centre in `hdb.csv`), `hdb.csv` puts the blocks 107 m from the matched TANGLIN HALT MARKET; with
that point the Q4 class would change for no stage 1 building and, over all five files, for 2
buildings (41 and 47 STIRLING RD, 22 sales, medium to near). The other two have no `hdb.csv`
block with their postcode, so their effect cannot be estimated.
An independent check supports the 104 matches: for the 80 centres located in an HDB block, the
`hdb.csv` block with the same postcode is flagged `market_hawker=Y` and lies 0-36 m (median 0 m)
from the `hawker_geo` point. The build requires every matched row to be approved, its `hawker_id`
to equal the contract ID, its row number to point at the named `hawker_geo` record and both
addresses to share a postcode; it fails if a `hawker_geo` record is used twice or an NEA centre has
no row. The 25 `hawker_geo` records outside the NEA list are reported, not loaded (see F-02).

**Buildings.** Exact match of HE's canonical `block` + `street_name` to canonical `blk_no` +
`street` in `hdb.csv`; no abbreviation rules are needed (stage 1: 7,921 of 7,921 addresses
found). A building keeps NULL coordinates, with a diagnostic, when:

| Reason | Rule | Stage 1 | All five (QA) |
|---|---|---:|---:|
| `no_hdb_geo_record` | Address not in `hdb.csv` (mostly blocks sold only in the 1990s, since demolished) | 0 | 172 |
| `geocoded_to_other_address` | `hdb.csv`'s `addr`, the address its geocoder actually matched, does not start with this block and street (HDB abbreviations expanded). Example: 2 BEACH RD was matched to "2 ANDOVER ROAD CHANGI BEACH CLUB" | 16 | 19 |
| `ambiguous_source_coordinate` | After that, a point still given to two or more addresses | 0 | 0 |
| `rejected_by_coordinate_review` | Reviewed cases the rules cannot see, in `coordinate_review.csv`: 1 and 3 BEACH RD were placed at Raffles Hotel, which shares their address | 2 | 2 |

All three rules use `hdb.csv` only, so a building gets the same answer in every stage.

*Why an address check and not a distance threshold.* A threshold such as "more than 500 m from
every other building of the town" finds only points that are kilometres off; it misses points
placed at a neighbouring address and flags genuinely remote blocks. The address check uses
`hdb.csv`'s own record of what each point is and needs no threshold. On all 9,853 loaded buildings
it flags 19, each matched to a different block or road. HDB postcodes normally end with the block
number, so the 87 loaded buildings whose `hdb.csv` postcode does not were also read one by one:
apart from cases the rules already catch, only 1 and 3 BEACH RD were clearly wrong (geocoded to
Raffles Hotel, which shares their address), and they are in `coordinate_review.csv`. The distance
test is kept as a warning only: `isolated_from_town` flags a building more than 500 m from every
other building of its town (real data: median 50 m, 99.9th percentile about 200 m); in stage 1
these are 15 BEACH RD and 464 UPP SERANGOON RD, whose points match their addresses.

The rules keep `(latitude, longitude)` unique among loaded buildings, so the
`fd_probe_coordinate_pairs_shared_by_buildings` probe is 0 (design_decisions.md D2). Sales of
these buildings stay in the database for Q1-Q3; they only have no proximity class.

All coordinates must be finite, not (0,0), and inside lat 1.15-1.50, lon 103.5-104.1; every
point in both sources is. **Distances** use the contract's Haversine with R = 6,371,008.8 m in
the same evaluation order as `housing.haversine_m`, written with shortest round-trip float text.

## Results

| | Stage 1 (2015-2016) | All five files (QA, see limitations) |
|---|---:|---:|
| Buildings / geocoded | 7,921 / 7,903 | 10,025 / 9,832 |
| Transactions with a proximity class | 37,057 of 37,153 | 974,040 of 989,492 (98.4%) |
| Centres / geocoded / fresh market (all geocoded) | 107 / 104 / 81 | 107 / 104 / 81 |
| `building_hawker` rows | 821,912 | 1,022,528 |

Evidence: `evidence/stage1_2015_2016/` (`validation.json`, `diagnostics.csv`,
`distance_analysis.md`, `postgres_import.json`) and `evidence/qa_all_five_live2017/`
(`validation.json`, `diagnostics.csv`, `distance_analysis.md`).

## Validation

`verify.py` re-reads a stage and checks: output hashes against the manifest; exact headers;
building IDs, towns and addresses identical to the HDB handoff, row by row; coordinates paired,
finite, inside Singapore and written as canonical float text; no coordinate pair shared by two
buildings; hawker IDs recomputed from the contract; canonical, unique centre name/address; the
complete matrix in key order; every distance within 0.001 m of an independent (atan2) Haversine
form. On stage 1 the largest difference is 3e-11 m. The database check
(`validate_loaded_data.sql`) allows 0.01 m.

The 16 unit tests cover distance values and class boundaries (500 m is medium, 1,000 m is far),
coordinate validation, the address check on real `hdb.csv` addresses, every crosswalk failure
rule, the coordinate rules, download retries, a full build on a synthetic fixture, determinism,
overwrite protection and tamper detection.

**PostgreSQL import (stage 1).** On PostgreSQL 17.11 (official Docker image) the unchanged
`001_schema.sql` was created and all six CSVs were imported in one transaction with
`HEADER match`, without errors. `validate_loaded_data.sql` passed: complete matrix, distances
within 0.01 m, `fd_probe_coordinate_pairs_shared_by_buildings` = 0. LI's Q1-Q6 all run; Q4
returns 45 rows (the 45 town/flat-type cells with both near and far sales) and Q5 keeps 10 of 26
towns. Exporting the three spatial tables back gave 0 differing rows (floats compared as exact
doubles). See `evidence/stage1_2015_2016/postgres_import.json`. This is a module check, not
Sun's loader.

## Issues met and how they were handled

| Issue | Handling |
|---|---|
| Names in `hawker_geo.csv` differ from the NEA names for 87 centres | Matched on postcode plus identical block/street text, reviewed once and approved in WU's candidate crosswalk; never fuzzy-matched at run time |
| 3 NEA centres have no `hawker_geo` record | Kept with NULL coordinates; a nearby successor centre is a different place and is not used |
| `hdb.csv` sometimes geocoded a block to another address (2 BEACH RD to a Changi beach club, 52/54 KENT RD to a Kent Ridge condominium) | Address check on `hdb.csv`'s own `addr`; 19 buildings over all five files |
| 1 and 3 BEACH RD were placed at Raffles Hotel, which has the same address | Listed in `coordinate_review.csv` with the evidence |
| One point given to two addresses (e.g. 21 HOUGANG AVE 3 and 211 HOUGANG ST 21) | The `addr` shows whose point it is; a point still shared by two addresses would be dropped |
| Blocks sold in the 1990s are missing from `hdb.csv` | Kept with NULL coordinates and counted |
| Unsigned data.gov.sg storage links return 403 | `download.py` asks the public API for a fresh signed link, uses it once, never stores it, and checks the hash |
| The live 2017-onwards HDB file no longer matches HE's frozen copy | All-five results marked QA only (see limitations) |

## Known limitations

- **Static sources.** The NEA list is a 2016 snapshot and `hdb.csv` a historical building
  snapshot. They do not show which centres existed at each sale date. The NEA list matches the
  2015-2016 stage in time; for 2017+ sales it misses newer centres (proposal F-02 and
  `distance_analysis.md` give the size of this effect).
- **Rebuilt blocks.** `hdb.csv` has one point per address. 21 TEBAN GDNS RD has lease years
  1978 and 2013 in HE's profile and is listed in `hdb.csv` as completed in 2012, so its 54 sales
  of the 1978 block (1990-1999) get the new block's point. Stage 1 has only the 2013 block.
- **Straight-line distance**, not walking routes.
- **Coverage.** 172 addresses sold only in older files are not in `hdb.csv` (QA run: 1.3% of all
  transactions), and 21 more buildings have their `hdb.csv` point rejected.
- **Undetectable geocoding errors.** A point placed at another building with the same block
  number and road passes the address check. Two such cases were found by reading the rows with
  unusual postcodes; others whose postcode looks normal could remain, and checking them would
  need a source outside the prescribed data.
- **2017-onwards snapshot.** HE's frozen copy of the 2017-onwards file can no longer be
  downloaded (the live file has grown). `evidence/qa_all_five_live2017/` was therefore built with
  HE's pipeline from his four frozen files plus the 2026-10-22 live copy of the fifth (+334
  transactions, +1 address). It is QA evidence, not an official stage; rerun with the frozen file
  when available.

## Open decisions

Not settled by this module; the evidence is in `evidence/*/distance_analysis.md`:

- Hawker inventory: NEA-only (current contract) or adding the 25 geo-only centres
  ([proposal F-02](../../../docs/architecture/proposals/F02_hawker_coverage.md)). Owners: Chen, LI.
- Bounded far class / maximum effective distance
  ([proposal F-03](../../../docs/architecture/proposals/F03_proximity_semantics.md)). The nearest
  fresh-market distance has p95 = 5.1-5.3 km, so the proposal's "p95, capped at 2,000 m" rule
  gives 2,000 m. Owners: Chen, LI.
