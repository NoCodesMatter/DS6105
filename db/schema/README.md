# Database schema

PostgreSQL schema for Task 1, contract **1.0.0-draft.2** (pending team approval at Gate 0).
The interface specification (tables, CSV headers, ID rules, load order) is
[docs/architecture/schema_contract.md](../../docs/architecture/schema_contract.md).

| File | Purpose | Used by |
|---|---|---|
| `create_database.sql` | Creates a new database and runs `001_schema.sql` (psql) | Sun |
| `001_schema.sql` | Schema `housing`: 6 base tables, constraints, 2 functions (`haversine_m`, `proximity_class`), 3 views (`building_hawker_proximity`, `nearest_hawker`, `nearest_market_hawker`) | everyone |
| `contract.py` | Shared Python helpers: canonical text, deterministic UUIDv5 IDs, exact CSV column order and load order (Python 3.10+, standard library only) | HE, Chen |
| `validate_loaded_data.sql` | Read-only acceptance checks after a data stage is loaded | Sun |

Normal form: 3NF; BCNF under stated assumptions. Two dependencies are Pending Validation on real
data; see [design_decisions.md §D2](../../docs/architecture/design_decisions.md).
No optional indexes and no extensions (no PostGIS).

## Create the database

From the project root, create a **new** database (choose a unique name):

```sh
psql -X -v ON_ERROR_STOP=1 -d postgres -v database_name=sd6105_housing -f db/schema/create_database.sql
```

Or create the schema in an existing **empty** database (also works in pgAdmin):

```sh
psql -X -v ON_ERROR_STOP=1 -d your_empty_database -f db/schema/001_schema.sql
```

Both fail on existing objects instead of resetting, dropping or modifying an existing `housing`
schema. Schema creation is atomic. Creating a named database needs the CREATEDB privilege.
Queries must use the `housing.` prefix or `SET search_path TO housing;`.

## Load order and IDs

Load the six CSVs in this order, in one transaction per stage:

1. `town`
2. `hdb_building`
3. `hdb_flat`
4. `resale_transaction`
5. `hawker_centre`
6. `building_hawker`

Generate IDs with `contract.py` (`building_id`, `flat_id`, `hawker_id`, `transaction_id`) so every
producer derives identical keys. Do not use `ON CONFLICT DO NOTHING` to hide mismatches. The exact
CSV rules are in the contract.

## Check a loaded stage

```sh
psql -X -v ON_ERROR_STOP=1 -d your_project_database -f db/schema/validate_loaded_data.sql
```

The script is read-only. It **fails** if:
- no transactions are loaded;
- no geocoded hawker or fresh-market hawker exists;
- the building × hawker distance matrix is incomplete;
- a stored distance differs from the coordinates by more than 0.01 m;
- an estimated remaining lease breaks the documented formula.

It **reports, without failing**:
- missing coordinates and unknown leases;
- three dependency probes (`fd_probe_buildings_with_multiple_lease_years`,
  `fd_probe_coordinate_pairs_shared_by_buildings`, `transactions_before_lease_commencement_year`);
- nearest-class counts.

Run it outside timed experiments, because the full distance check takes several seconds at full
size. Passing it does not prove that source matching is correct or that query results are right.

## Status and open decisions

- **Final for use now:** table structure, CSV headers, ID serialisation, load order, constraints.
- **Pending team decisions:** see
  [docs/architecture/completion_report.md](../../docs/architecture/completion_report.md).
  - Hawker inventory (proposal F-02) and the bounded proximity class (proposal F-03): **not adopted**.
  - Approval of the hawker crosswalk (Chen).
