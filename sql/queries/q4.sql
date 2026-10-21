-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 4 (Q4)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A & Schema Contract Requirement:
--   Find the price differential between HDB flats of closest proximity class
--   ('near': [0, 500) m) and HDB flats in the furthest proximity class
--   ('far': >= 1000 m).
--   Output columns must be:
--     town, flat_type, avg_price_near_hawker, avg_price_far_hawker, price_diff_percentage
--
-- Anti-Fan-Out Guarantee:
--   Joins housing.nearest_hawker (DISTINCT ON building_id) so each building
--   receives at most one proximity class, guaranteeing zero transaction duplication.
-- =============================================================================

WITH town_flat_proximity_prices AS (
    SELECT
        b.town_name AS town,
        f.flat_type,
        AVG(r.resale_price) FILTER (WHERE nh.proximity_class = 'near') AS raw_avg_near,
        AVG(r.resale_price) FILTER (WHERE nh.proximity_class = 'far') AS raw_avg_far
    FROM housing.resale_transaction AS r
    JOIN housing.hdb_flat AS f
        USING (flat_id)
    JOIN housing.hdb_building AS b
        USING (building_id)
    JOIN housing.nearest_hawker AS nh
        USING (building_id)
    WHERE nh.proximity_class IN ('near', 'far')
    GROUP BY
        b.town_name,
        f.flat_type
)
SELECT
    town,
    flat_type,
    ROUND(raw_avg_near, 2) AS avg_price_near_hawker,
    ROUND(raw_avg_far, 2) AS avg_price_far_hawker,
    ROUND(
        (raw_avg_near - raw_avg_far) * 100.0 / NULLIF(raw_avg_far, 0),
        2
    ) AS price_diff_percentage
FROM town_flat_proximity_prices
WHERE raw_avg_near IS NOT NULL
  AND raw_avg_far IS NOT NULL
ORDER BY
    town ASC,
    flat_type ASC;

