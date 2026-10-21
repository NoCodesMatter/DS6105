-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Consolidated Queries Q1–Q6
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
-- Submission: Task 3 Supplementary SQL Workload
-- =============================================================================

-- =============================================================================
-- Q1: Price-per-Square-Meter Across Towns
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


-- =============================================================================
-- Q2: Remaining Lease vs. Transaction Price
-- =============================================================================
WITH categorized_sales AS (
    SELECT
        b.town_name AS town,
        CASE
            WHEN r.remaining_lease_months IS NULL THEN 'unknown'
            WHEN r.remaining_lease_months < 600 THEN 'less_than_50_years'
            WHEN r.remaining_lease_months <= 840 THEN 'between_50_and_70_years'
            ELSE 'more_than_70_years'
        END AS remaining_lease_bucket,
        r.resale_price,
        r.resale_price / f.floor_area_sqm AS price_per_sqm
    FROM housing.resale_transaction AS r
    JOIN housing.hdb_flat AS f
        USING (flat_id)
    JOIN housing.hdb_building AS b
        USING (building_id)
)
SELECT
    town,
    remaining_lease_bucket,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resale_price)::numeric,
        2
    ) AS median_resale_price,
    ROUND(AVG(price_per_sqm), 2) AS avg_price_per_sqm,
    COUNT(*) AS total_transaction_volume
FROM categorized_sales
GROUP BY
    town,
    remaining_lease_bucket
ORDER BY
    town ASC,
    CASE remaining_lease_bucket
        WHEN 'less_than_50_years' THEN 1
        WHEN 'between_50_and_70_years' THEN 2
        WHEN 'more_than_70_years' THEN 3
        ELSE 4
    END ASC;


-- =============================================================================
-- Q3: Resale Price for Towns with Large Flats
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


-- =============================================================================
-- Q4: Hawker Centre Proximity Effect
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


-- =============================================================================
-- Q5: Town Level Price Near Fresh Market Hawkers
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


-- =============================================================================
-- Q6: Comprehensive Six-Table Urban Amenity & Housing Valuation Analysis
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

