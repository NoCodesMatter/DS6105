-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 6 (Q6)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A & Task 3.1 Requirement:
--   Define an analytical query that explicitly joins ALL SIX base tables:
--     1. housing.town
--     2. housing.hdb_building
--     3. housing.hdb_flat
--     4. housing.resale_transaction
--     5. housing.building_hawker
--     6. housing.hawker_centre
--
-- Analytical Scope:
--   Comprehensive Urban Amenity & Housing Valuation Analysis:
--   For each town and nearest-hawker proximity class, examine unit resale price
--   (SGD/sqm), median price, remaining lease, and walkable hawker accessibility
--   (average hawker centres and fresh-market produce stalls within 1,000 m).
--
-- Anti-Fan-Out Guarantee:
--   Spatial relations (building_hawker x hawker_centre) are pre-aggregated to
--   building grain inside building_amenity_profile before joining resale_transaction.
-- =============================================================================

WITH building_amenity_profile AS (
    SELECT
        bh.building_id,
        MIN(bh.distance_m) AS nearest_hawker_distance_m,
        housing.proximity_class(MIN(bh.distance_m)) AS nearest_proximity_class,
        COUNT(*) FILTER (WHERE bh.distance_m < 1000.0) AS hawkers_within_1km,
        COUNT(*) FILTER (
            WHERE bh.distance_m < 1000.0 AND h.market_produce_stalls > 0
        ) AS fresh_market_hawkers_within_1km,
        COALESCE(
            SUM(h.market_produce_stalls) FILTER (WHERE bh.distance_m < 1000.0),
            0
        ) AS market_stalls_within_1km
    FROM housing.building_hawker AS bh
    JOIN housing.hawker_centre AS h
        USING (hawker_id)
    GROUP BY
        bh.building_id
)
SELECT
    t.town_name AS town,
    bap.nearest_proximity_class AS proximity_class,
    COUNT(r.transaction_id) AS transaction_volume,
    COUNT(DISTINCT b.building_id) AS geocoded_buildings_sold,
    ROUND(AVG(r.resale_price), 2) AS avg_resale_price,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.resale_price)::numeric,
        2
    ) AS median_resale_price,
    ROUND(AVG(r.resale_price / f.floor_area_sqm), 2) AS avg_price_per_sqm,
    ROUND(AVG(r.remaining_lease_months / 12.0), 1) AS avg_remaining_lease_years,
    ROUND(AVG(bap.hawkers_within_1km), 2) AS avg_hawkers_within_1km,
    ROUND(AVG(bap.fresh_market_hawkers_within_1km), 2) AS avg_fresh_market_hawkers_within_1km,
    ROUND(AVG(bap.market_stalls_within_1km), 1) AS avg_market_stalls_within_1km
FROM housing.town AS t
JOIN housing.hdb_building AS b
    ON b.town_name = t.town_name
JOIN building_amenity_profile AS bap
    ON bap.building_id = b.building_id
JOIN housing.hdb_flat AS f
    ON f.building_id = b.building_id
JOIN housing.resale_transaction AS r
    ON r.flat_id = f.flat_id
WHERE bap.nearest_proximity_class IS NOT NULL
GROUP BY
    t.town_name,
    bap.nearest_proximity_class
ORDER BY
    t.town_name ASC,
    CASE bap.nearest_proximity_class
        WHEN 'near' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'far' THEN 3
    END ASC;

