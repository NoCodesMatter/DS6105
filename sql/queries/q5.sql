-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 5 (Q5)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A & Schema Contract Requirement:
--   For all towns, compute the average resale price per proximity class
--   ('near', 'medium', 'far') for flats that are in proximity to a hawker with
--   fresh market stalls (market_produce_stalls > 0). Filter the results to only
--   return towns where the average resale price exceeds a budget limit (in SGD)
--   of your choice, making sure the result is neither empty nor contains all towns.
--
-- Design & Budget Filter:
--   1. Uses housing.nearest_market_hawker (filtered for market_produce_stalls > 0)
--      with WHERE proximity_class IS NOT NULL, compatible with both Contract
--      1.0.0-draft.2 and Proposal F-03.
--   2. A town-level budget threshold of SGD 450,000.00 selects higher-value
--      towns (e.g., BUKIT TIMAH, BISHAN, CENTRAL AREA) and excludes lower-priced
--      towns, returning a non-empty proper subset across loaded stages.
-- =============================================================================

WITH fresh_market_sales AS (
    SELECT
        b.town_name AS town,
        nmh.proximity_class,
        r.resale_price
    FROM housing.resale_transaction AS r
    JOIN housing.hdb_flat AS f
        USING (flat_id)
    JOIN housing.hdb_building AS b
        USING (building_id)
    JOIN housing.nearest_market_hawker AS nmh
        USING (building_id)
    WHERE nmh.proximity_class IS NOT NULL
),
qualifying_towns AS (
    SELECT
        town,
        ROUND(AVG(resale_price), 2) AS town_avg_resale_price
    FROM fresh_market_sales
    GROUP BY
        town
    HAVING AVG(resale_price) > 450000.00
)
SELECT
    fms.town,
    fms.proximity_class,
    ROUND(AVG(fms.resale_price), 2) AS avg_resale_price,
    COUNT(*) AS transaction_count,
    qt.town_avg_resale_price
FROM fresh_market_sales AS fms
JOIN qualifying_towns AS qt
    USING (town)
GROUP BY
    fms.town,
    fms.proximity_class,
    qt.town_avg_resale_price
ORDER BY
    qt.town_avg_resale_price DESC,
    fms.town ASC,
    CASE fms.proximity_class
        WHEN 'near' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'far' THEN 3
    END ASC;

