-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 3 (Q3)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A & design_decisions.md §D1 Requirement:
--   Identify the top 10 towns with the highest average floor area for 3-Room
--   flats using LIMIT. For these top towns, retrieve the highest resale
--   transaction amount per year for a 3-Room flat using WITH / subqueries.
--
-- Ranking Grain:
--   Following design_decisions.md §D1, the top-10 town ranking averages
--   floor_area_sqm over distinct observed 3-Room flat profiles in housing.hdb_flat
--   (with town_name ASC as deterministic tie-breaker).
-- =============================================================================

WITH top_10_large_3room_towns AS (
    SELECT
        b.town_name AS town,
        ROUND(AVG(f.floor_area_sqm), 2) AS avg_3room_floor_area_sqm
    FROM housing.hdb_flat AS f
    JOIN housing.hdb_building AS b
        USING (building_id)
    WHERE f.flat_type = '3 ROOM'
    GROUP BY
        b.town_name
    ORDER BY
        AVG(f.floor_area_sqm) DESC,
        b.town_name ASC
    LIMIT 10
)
SELECT
    t10.town,
    t10.avg_3room_floor_area_sqm,
    EXTRACT(YEAR FROM r.sale_month)::integer AS transaction_year,
    MAX(r.resale_price) AS highest_resale_price,
    COUNT(*) AS transaction_count
FROM top_10_large_3room_towns AS t10
JOIN housing.hdb_building AS b
    ON b.town_name = t10.town
JOIN housing.hdb_flat AS f
    USING (building_id)
JOIN housing.resale_transaction AS r
    USING (flat_id)
WHERE f.flat_type = '3 ROOM'
GROUP BY
    t10.town,
    t10.avg_3room_floor_area_sqm,
    EXTRACT(YEAR FROM r.sale_month)::integer
ORDER BY
    t10.avg_3room_floor_area_sqm DESC,
    t10.town ASC,
    transaction_year ASC;
