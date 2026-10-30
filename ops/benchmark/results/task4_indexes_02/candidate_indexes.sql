-- =============================================================================
-- SD6103 Data Systems Project — Task 4 candidate indexes
-- Module owner: Lu Wenrui (Performance Optimization & Reporting)
-- Target schema: housing (contract 1.0.0-draft.2)
--
-- DO NOT run this on the official Task 3 baseline database until all 150
-- baseline timings are complete. Indexes created implicitly by PRIMARY KEY /
-- UNIQUE constraints are part of the baseline schema and are not listed here.
--
-- Each index is evaluated ON ITS OWN (create -> ANALYZE -> 5 timed runs of
-- Q1–Q6 -> drop) and then all together; see analysis/index_experiment.py.
-- Rationale and plan evidence: sql/indexes/README.md
-- =============================================================================

-- I1  Q1: range filter on sale_month (3-year window = a small fraction of rows).
CREATE INDEX idx_rt_sale_month
    ON housing.resale_transaction (sale_month);

-- I2  Q1–Q6: FK join resale_transaction.flat_id -> hdb_flat.
--     PostgreSQL does not index foreign-key columns automatically.
CREATE INDEX idx_rt_flat_id
    ON housing.resale_transaction (flat_id);

-- I3  Q1, Q3: equality filter on flat_type ('3 ROOM'; '4 ROOM','5 ROOM').
CREATE INDEX idx_flat_type_building
    ON housing.hdb_flat (flat_type, building_id);

-- I4  Q4, Q5 (views nearest_hawker / nearest_market_hawker) and Q6:
--     matches the DISTINCT ON (building_id) ... ORDER BY building_id,
--     distance_m, hawker_id order, so the ~0.9M-row sort can be replaced by
--     an ordered index scan.
CREATE INDEX idx_bh_building_distance
    ON housing.building_hawker (building_id, distance_m, hawker_id);

-- I5  Q3: join hdb_building on town_name for the top-10 towns.
CREATE INDEX idx_building_town
    ON housing.hdb_building (town_name);
