-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 1 (Q1)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A Requirement:
--   Calculate the average price per square meter for 4-Room and 5-Room flats
--   sold within a 3-year range available in your loaded data.
--
-- Design & Compatibility:
--   Stage 1 contains dataset d_ea9ed51da2787afaf8e51f827c304208 (2015-01 to 2016-12).
--   Stage 2 adds 2012-03 to 2014-12, and Stage 3 adds 2017-01 onwards.
--   A 3-year calendar window [2014-01-01, 2016-12-01] (inclusive of all months
--   in 2014, 2015, and 2016) executes cleanly on Stage 1 and seamlessly covers
--   all 36 months from Stage 2 through Stage 5 without modifying query text.
-- =============================================================================

SELECT
    b.town_name AS town,
    f.flat_type,
    COUNT(*) AS transaction_count,
    ROUND(AVG(r.resale_price / f.floor_area_sqm), 2) AS avg_price_per_sqm,
    ROUND(SUM(r.resale_price) / SUM(f.floor_area_sqm), 2) AS area_weighted_price_per_sqm
FROM housing.resale_transaction AS r
JOIN housing.hdb_flat AS f
    USING (flat_id)
JOIN housing.hdb_building AS b
    USING (building_id)
WHERE f.flat_type IN ('4 ROOM', '5 ROOM')
  AND r.sale_month >= DATE '2014-01-01'
  AND r.sale_month <= DATE '2016-12-01'
GROUP BY
    b.town_name,
    f.flat_type
ORDER BY
    b.town_name ASC,
    f.flat_type ASC;
