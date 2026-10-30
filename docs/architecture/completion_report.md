# Task 1 completion and handover

Status: 2026-10-30 · Schema contract **1.0.0**, frozen at Gate 0 for the Task 3 baseline and
Task 4 experiments.

## 1. Ready to use

| Deliverable | Location |
|---|---|
| PostgreSQL creation scripts (6 tables, constraints, 2 functions, 3 views) | `db/schema/create_database.sql`, `db/schema/001_schema.sql` |
| Exact CSV headers, types, null rules, load order | [schema_contract.md](schema_contract.md) |
| Deterministic ID helpers and CSV column order | `db/schema/contract.py` |
| Loaded-stage acceptance checks | `db/schema/validate_loaded_data.sql` |
| Conceptual ER and logical schema diagrams | [conceptual_er.png](conceptual_er.png), [er_diagram.png](er_diagram.png) (+ draw.io) |
| Task 1 report section | [task1_report.md](task1_report.md) |

Any further change to the schema needs a new contract version and review by the affected owners.
After the freeze, a change also invalidates Task 3/4 measurements taken on the old version.

## 2. Gate 0 decisions (2026-10-30)

| Item | Decision | Agreed by |
|---|---|---|
| Hawker inventory (F-02) | **Option A:** only the 107 NEA centres. The 25 newer geo-only centres are not loaded; this is reported as a coverage limitation. | Chen, LI, WU |
| Hawker crosswalk | **104 matches approved** by Chen (2026-10-23). 3 NEA centres stay unmatched with NULL coordinates. | Chen |
| Proximity classes (F-03) | **Option B:** near [0,500), medium [500,1000), far [1000,2000] m. Beyond 2,000 m there is no class (NULL). About 29% of transactions have no class. | Chen, LI, WU |
| 500 m / 1000 m thresholds | Kept; checked against real nearest distances | Chen |
| Nearest-view definition | Lu's rewrite adopted: the class is computed after `DISTINCT ON` (identical rows, faster) | Lu, WU |
| Q3 / Q4 / Q5 semantics | As in LI's frozen `sql/queries/`: Q3 profile-weighted, Q4 near vs far of the nearest centre, Q5 nearest fresh-market centre with NULL classes excluded | LI |

Details: [decision F-02](proposals/F02_hawker_coverage.md),
[decision F-03](proposals/F03_proximity_semantics.md), [design_decisions.md](design_decisions.md).

## 3. Still open

| Item | State | Owner |
|---|---|---|
| building → lease_commence_year; coordinate uniqueness (BCNF of `hdb_flat` / `hdb_building`) | Pending Validation. Read the probes in `validate_loaded_data.sql` on the five-file database. | HE / Sun (run), WU (conclude) |
| Candidate value bounds (dates, storeys, area, price, Singapore envelope) | Not enforced; listed in design_decisions.md §D5 | HE, Chen |

## 4. Hand-off per member

| Member | Next action |
|---|---|
| Sun | **Rebuild the database with contract 1.0.0 before any official Task 3 timing.** Load the spatial `hdb_building.csv` (with coordinates), not the HDB-stage one. Use `HEADER MATCH`, keep `work_mem` and the other settings fixed, and follow Lu's timing method (`sql/indexes/README.md`). Run `validate_loaded_data.sql` after each stage, outside timed runs. |
| LI | Re-run Q1–Q6 on 1.0.0. Check that the Q5 budget leaves some but not all towns at **every** stage: it returns 0 rows on the 1990–2016 database. Align the hand-off text with the SQL (Q5 filters on the town average; Q1/Q3 field names). |
| Lu | Task 4 compares against the 1.0.0 baseline. The view rewrite is already in the schema; the candidate index `building_hawker(building_id, distance_m, hawker_id)` is not. |
| Chen | No schema action. Keep the approved crosswalk and the 2,000 m rule in the spatial README. |
| HE | Send the frozen 2017-onwards file to Lu. Report the FD probe counts once the five files are loaded. |
| WU | Review end-to-end consistency before the final report; finalise the normal-form statement from the probe results. |

## 5. Known limitations

- **Static sources.** The hawker list is the static 2016 NEA list and hdb.csv is a historical
  building snapshot. Neither proves access at the sale date or a causal price effect. Newer
  estates lose centres that opened after 2016.
- **Distance.** Distances are straight-line Haversine distances, not walking routes. Beyond
  2,000 m a sale has no proximity class.
- **Observed profiles.** An HDB Flat is an observed profile, not an identified dwelling.
