# SQL Queries & Business Analysis Module (`sql/queries/`)

**Module Owner:** LI JIAHANG — SQL Query & Business Analysis Owner  
**Target Schema Contract:** `1.0.0-draft.2` (`db/schema/001_schema.sql`)  
**Assignment Scope:** Task 3.1 SQL Queries (`Q1`–`Q6`), semantic correctness validation, business analysis insights, and Task 3/4 benchmark handoffs for Sun NengKe (`ops/`) and Lu Wenrui (`sql/indexes/`).

> [!IMPORTANT]
> **Key Module Deliverables & Handoff Navigation:**
> - 📄 **Formal Handoff Report:** [`handoff.md`](handoff.md) — Complete English technical documentation, 6-table integrity proofs, zero fan-out verification, Stage 1 empirical results, and analytical business insights.
> - 🖼️ **Terminal Result Screenshots:** [`evidence/screenshots/`](evidence/screenshots/) — Professional, high-resolution execution screenshots for Q1–Q6 (`q1_result.png` to `q6_result.png`).
> - 📊 **Execution Metrics & Summary:** [`evidence/stage1_query_summary.json`](evidence/stage1_query_summary.json) — Structured query execution metrics, row counts, and Proposal F-03 sensitivity analysis.

---

## 1. Module Overview & Responsibilities

As defined in `.context_ref/Task_Allocation.md` §3.4 and `docs/architecture/completion_report.md` §3, this module is accountable for:
1. Translating Appendix A's query requirements into valid, readable, standard PostgreSQL 15+ SQL queries (`q1.sql` to `q6.sql`).
2. Ensuring exact compliance with the Schema Contract `1.0.0-draft.2` and preventing join-induced transaction multiplication (anti-fan-out).
3. Providing a comprehensive analytical query (`q6.sql`) that genuinely joins all six base tables in the relational schema.
4. Implementing an automated test runner (`verify_queries.py`) with a full 6-table synthetic fixture dataset and Stage 1 real-data evaluation pipeline.
5. Delivering empirical insights for each query based on evaluated datasets.

---

## 2. Query Inventory & Contract Design Specifications

| Query | File | Base Tables & Views Used | Primary Analytical Objective | Output Schema |
|:---|:---|:---|:---|:---|
| **Q1** | `q1.sql` | `resale_transaction`, `hdb_flat`, `hdb_building` | Average unit price (SGD/sqm) across towns for 4-Room and 5-Room flats within a 3-year window. | `town, flat_type, avg_price_per_sqm, transaction_volume, town_avg_price_per_sqm` |
| **Q2** | `q2.sql` | `resale_transaction`, `hdb_flat`, `hdb_building` | Resale price and transaction volume grouped by town and remaining-lease buckets, with exact median price. | `town, remaining_lease_bucket, median_resale_price, avg_price_per_sqm, total_transaction_volume` |
| **Q3** | `q3.sql` | `hdb_flat`, `hdb_building`, `resale_transaction` | Identify top 10 towns by average floor area of 3-Room profiles, then retrieve annual maximum resale prices in those towns. | `town, rank_by_avg_area, avg_floor_area_sqm, resale_year, max_resale_price` |
| **Q4** | `q4.sql` | `resale_transaction`, `hdb_flat`, `hdb_building`, `nearest_hawker` | Compare average prices between 'near' (<500m) and 'far' (>=1000m) nearest-hawker proximity classes by town and flat type. | `town, flat_type, avg_price_near_hawker, avg_price_far_hawker, price_diff_percentage` |
| **Q5** | `q5.sql` | `resale_transaction`, `hdb_flat`, `hdb_building`, `nearest_market_hawker` | Resale prices per proximity class for hawkers with fresh-market stalls (`market_produce_stalls > 0`), filtered by a budget limit (> SGD 450,000) that retains a non-empty proper subset of towns. | `town, proximity_class, avg_resale_price, transaction_count, town_avg_resale_price` |
| **Q6** | `q6.sql` | `town`, `hdb_building`, `hdb_flat`, `resale_transaction`, `building_hawker`, `hawker_centre` | Comprehensive 6-table spatial amenity & valuation analysis: assesses unit price, median price, remaining lease, and 1km hawker/produce stall density per town and proximity class. | `town, proximity_class, transaction_volume, geocoded_buildings_sold, avg_resale_price, median_resale_price, avg_price_per_sqm, avg_remaining_lease_years, avg_hawkers_within_1km, avg_fresh_market_hawkers_within_1km, avg_market_stalls_within_1km` |
| **All**| `all_queries.sql` | All tables & views | Consolidated SQL script combining Q1–Q6 sequentially for Task 3 submission. | Concatenated output of Q1–Q6 |

---

## 3. Key Semantic & Modeling Assumptions

### 3.1 Q1 Three-Year Range vs. Stage 1 Compatibility
- **Requirement:** A 3-year range available in the loaded data.
- **Implementation:** `sale_month >= DATE '2014-01-01' AND sale_month <= DATE '2016-12-01'` (36 calendar months).
- **Rationale:** Stage 1 loads dataset `d_ea9ed51da2787afaf8e51f827c304208` (2015-01 to 2016-12, 24 months). Filtering for 2014–2016 executes cleanly on Stage 1 (returning 37,153 records) and seamlessly captures the complete 36-month window once Stage 2 (`2012_03_2014`) is added, keeping the query text strictly frozen across all benchmark stages.

### 3.2 Q2 Remaining Lease Bucketing & Unknown Handling
- **Buckets Defined:**
  - `less_than_50_years`: `remaining_lease_months < 600`
  - `between_50_and_70_years`: `remaining_lease_months >= 600 AND remaining_lease_months <= 840`
  - `more_than_70_years`: `remaining_lease_months > 840`
  - `unknown`: `remaining_lease_months IS NULL`
- **Audit-Proof Row Conservation:**
  Across the five raw HDB files, exactly 51 historical transactions have sale dates preceding lease commencement years (`lease_basis = 'unknown'`). Retaining the `unknown` bucket guarantees `SUM(total_transaction_volume) = COUNT(*)` across all stages.
- **Exact Median:** Computed via `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resale_price)`.

### 3.3 Q3 Ranking Grain (Flat Profiles vs. Transactions)
- In accordance with `docs/architecture/design_decisions.md §D1`, the top 10 towns are ranked by `AVG(floor_area_sqm)` across distinct observed flat profiles in `housing.hdb_flat` (with `town_name ASC` as a deterministic tie-breaker).
- This measures architectural design variety per town, avoiding transaction-volume skew. Annual maximum prices are then extracted for transactions within those towns.

### 3.4 Q4 & Q5 Anti-Fan-Out & Proximity Semantics
- **Q4 Anti-Fan-Out:** Joins `housing.nearest_hawker` (`DISTINCT ON (building_id)`), ensuring each building and each transaction maps to exactly one nearest hawker.
- **Q5 Fresh-Market Qualification:** Joins `housing.nearest_market_hawker` (which filters `market_produce_stalls > 0`) and includes `WHERE proximity_class IS NOT NULL`, maintaining forward compatibility with both Contract `1.0.0-draft.2` and Proposal `F-03` (Option B bounded proximity).
- **Budget Threshold:** `HAVING AVG(resale_price) > 450000.00` filters towns at the aggregated level, producing a non-empty proper subset of towns across all stages.

### 3.5 Q6 Genuine Six-Table Join & Anti-Fan-Out CTE
- **Base Tables:** Explicitly joins `housing.town`, `housing.hdb_building`, `housing.hdb_flat`, `housing.resale_transaction`, `housing.building_hawker`, and `housing.hawker_centre`.
- **Pre-Aggregation:** Spatial tables (`building_hawker` and `hawker_centre`) are pre-aggregated to building grain in CTE `building_amenity_profile` before joining transaction data. This guarantees zero row explosion and exact transaction reconciliation.

---

## 4. Execution & Automated Verification

### 4.1 Automated Test Runner (`verify_queries.py`)
The verification script provides end-to-end automated testing using Python standard library and `psql`:

```bash
# 1. Run full synthetic verification on a clean 6-table test database:
python sql/queries/verify_queries.py

# 2. Run both synthetic tests and Stage 1 real data tests (exports CSVs and markdown insights):
python sql/queries/verify_queries.py --run-stage1
```

### 4.2 Automated Quality Gates
`verify_queries.py` enforces five automated quality gates:
1. **Zero SQL Errors:** All 6 queries execute with returncode 0.
2. **Schema Fidelity:** Exact output column names and ordering match `EXPECTED_COLUMNS`.
3. **Q2 Row Conservation:** `SUM(total_transaction_volume) == COUNT(*) FROM housing.resale_transaction`.
4. **View Anti-Fan-Out:** `COUNT(*) - COUNT(DISTINCT building_id) == 0` on nearest-hawker views.
5. **Q5 Proper Subset:** `0 < COUNT(DISTINCT town) < Total Towns`.
6. **Q6 Six-Table Coverage:** PostgreSQL `EXPLAIN (FORMAT JSON)` verifies presence of all 6 physical base tables.

### 4.3 Manual Execution via `psql`
```bash
# Execute against an integrated database:
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/all_queries.sql

# Execute individual queries:
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q1.sql
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q2.sql
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q3.sql
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q4.sql
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q5.sql
psql -X -v ON_ERROR_STOP=1 -d sd6105_housing -f sql/queries/q6.sql
```

---

## 5. Artifacts & Generated Reports

- **Individual Queries:** `sql/queries/q1.sql` through `sql/queries/q6.sql`
- **Consolidated Submission:** `sql/queries/all_queries.sql`
- **Test Runner:** `sql/queries/verify_queries.py`
- **QA & Empirical Insights:** `.sql-qa/` (ignored from Git)
  - `.sql-qa/stage1_q1_q3_results.md`: Empirical insights report on Stage 1 data.
  - `.sql-qa/q1_stage1_result.csv`: Q1 Stage 1 full result export.
  - `.sql-qa/q2_stage1_result.csv`: Q2 Stage 1 full result export.
  - `.sql-qa/q3_stage1_result.csv`: Q3 Stage 1 full result export.

---

## 6. Known Limitations & Gate 2 Handoff Notes

1. **Spatial Data Prerequisite (Q4–Q6):** Full execution of Q4, Q5, and Q6 on real data requires Chen YuChi's spatial pipeline (`src/etl/spatial/`) to populate `hawker_centre.csv` and `building_hawker.csv`. Our queries have been verified against the synthetic 6-table fixture.
2. **Frozen Benchmark Queries:** Once verified, these queries are frozen for Sun NengKe's 150-run benchmark tests in `ops/` and Lu Wenrui's index optimization analysis in `sql/indexes/`.

