# Task 1 completion and handover

Status: 2026-10-18 · Schema contract **1.0.0-draft.2** · Gate 0 (team approval) **open**.

## 1. Ready to use now

These are stable enough to build Task 2–4 work against. Changing any of them requires a contract
version change and review by the affected owners.

| Deliverable | Location |
|---|---|
| PostgreSQL creation scripts (6 tables, constraints, 2 functions, 3 views) | `db/schema/create_database.sql`, `db/schema/001_schema.sql` |
| Exact CSV headers, types, null rules, load order | [schema_contract.md](schema_contract.md) |
| Deterministic ID helpers and CSV column order | `db/schema/contract.py` |
| Loaded-stage acceptance checks | `db/schema/validate_loaded_data.sql` |
| Conceptual ER and logical schema diagrams | [conceptual_er.png](conceptual_er.png), [er_diagram.png](er_diagram.png) (+ draw.io) |
| Task 1 report section | [task1_report.md](task1_report.md) |

## 2. Not final: do not treat as decided

| Item | Current state | Decision owner |
|---|---|---|
| Schema contract as a whole | Draft 1.0.0-draft.2. Freezes as 1.0.0 at Gate 0. | All |
| Hawker inventory: 25 geo-only centres, 3 NEA centres without coordinates | Current contract: NEA's 107 centres only. Options in [proposal F-02](proposals/F02_hawker_coverage.md): **not adopted**. | Chen, LI |
| Hawker crosswalk (17 exact, 87 postcode-only, 3 unmatched) | All 107 entries **unapproved**. The 87 postcode-only pairs have identical block + street text. | Chen |
| Third proximity class without upper bound (far ≥ 1000 m) | Current contract unchanged. Bounded alternative in [proposal F-03](proposals/F03_proximity_semantics.md): **not adopted**. | Chen, LI |
| 500 m / 1000 m thresholds | Not yet checked against real nearest-distance data | Chen |
| building → lease_commence_year; coordinate uniqueness (BCNF of `hdb_flat` / `hdb_building`) | Pending Validation; reported by `validate_loaded_data.sql` | HE (data), WU |
| Q3 weighting (profiles vs transactions); Q4 = nearest centre; Q5 = nearest fresh-market centre | Proposed in [design_decisions.md](design_decisions.md) | LI |
| Candidate value bounds (dates, storeys, area, price, Singapore envelope) | Not enforced; listed in design_decisions.md §D5 | HE, Chen |

## 3. Hand-off per member

| Member | Needs from Task 1 | Next action |
|---|---|---|
| HE | Town / building / flat / transaction CSV specs, ID rules (`contract.py`), lease-basis rules | Generate the HDB-side CSVs. Report any address that maps to two towns and any building with more than one lease year. |
| Chen | Building enrichment hand-off, hawker and distance-pair CSV specs, crosswalk candidates, proposals F-02/F-03 | Approve or correct the crosswalk; choose the inventory option; supply geocoded buildings so the thresholds can be checked |
| LI | Relationships, the nearest views, modelling assumptions | Confirm the Q3/Q4/Q5 semantics; Q6 must join all six tables |
| Sun | Creation scripts, load order, `validate_loaded_data.sql` | Load stages in FK order, one transaction per stage, with `HEADER MATCH`; run the validation script after each stage, outside timed runs |
| Lu | PK/UNIQUE indexes are part of the baseline; no optional indexes exist | The 1.33 M-row distance matrix (~187 MB synthetic estimate) dominates Q4/Q5 cost; `building_hawker(building_id, distance_m)` is a Task 4 candidate |
| WU | Team decisions above | Implement the chosen F-02/F-03 options (DDL, contract, diagrams); bump the contract; freeze at Gate 0 |

## 4. Known limitations

- **Static sources.** The hawker list is the static 2016 NEA list and hdb.csv is a historical
  building snapshot. Neither proves access at the sale date or a causal price effect. Newer blocks
  may lack coordinates.
- **Straight-line distance.** Distances are Haversine distances, not walking routes.
- **Observed profiles.** An HDB Flat is an observed profile, not an identified dwelling, so repeat
  sales of one home cannot be inferred.
