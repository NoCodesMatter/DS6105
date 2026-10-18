-- Read-only architectural acceptance checks. No ETL, indexes, DDL or data changes.
-- For a fully populated stage. Missing locations are reported, never silently dropped.
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT 'buildings_without_coordinates' AS diagnostic, count(*) AS count
FROM housing.hdb_building WHERE latitude IS NULL
UNION ALL
SELECT 'hawkers_without_coordinates', count(*) FROM housing.hawker_centre WHERE latitude IS NULL
UNION ALL
SELECT 'transactions_without_spatial_coverage', count(*)
FROM housing.resale_transaction r JOIN housing.hdb_flat f USING (flat_id)
JOIN housing.hdb_building b USING (building_id) WHERE b.latitude IS NULL
UNION ALL
SELECT 'transactions_with_unknown_lease', count(*) FROM housing.resale_transaction WHERE lease_basis='unknown'
-- Pending-validation dependency probes (reported, never fatal). A nonzero count is
-- evidence AGAINST the dependency; zero on all five files is evidence FOR it.
UNION ALL
SELECT 'fd_probe_buildings_with_multiple_lease_years', count(*)
FROM (SELECT building_id FROM housing.hdb_flat GROUP BY building_id
      HAVING count(DISTINCT lease_commence_year) > 1) AS multi_lease
UNION ALL
SELECT 'fd_probe_coordinate_pairs_shared_by_buildings', count(*)
FROM (SELECT latitude, longitude FROM housing.hdb_building WHERE latitude IS NOT NULL
      GROUP BY latitude, longitude HAVING count(*) > 1) AS shared_location
UNION ALL
SELECT 'transactions_before_lease_commencement_year', count(*)
FROM housing.resale_transaction r JOIN housing.hdb_flat f USING (flat_id)
WHERE extract(year FROM r.sale_month) < f.lease_commence_year;

DO $$
DECLARE expected bigint; actual bigint;
BEGIN
    IF NOT EXISTS (SELECT FROM housing.resale_transaction) THEN
        RAISE EXCEPTION 'No transactions loaded: integration gate cannot pass';
    END IF;
    IF NOT EXISTS (SELECT FROM housing.hawker_centre WHERE latitude IS NOT NULL) THEN
        RAISE EXCEPTION 'No geocoded hawkers: Q4/Q5 cannot be accepted';
    END IF;
    IF NOT EXISTS (SELECT FROM housing.hawker_centre
                   WHERE latitude IS NOT NULL AND market_produce_stalls > 0) THEN
        RAISE EXCEPTION 'No geocoded fresh-market hawkers: Q5 cannot be accepted';
    END IF;
    SELECT (SELECT count(*) FROM housing.hdb_building WHERE latitude IS NOT NULL)
         * (SELECT count(*) FROM housing.hawker_centre WHERE latitude IS NOT NULL) INTO expected;
    SELECT count(*) INTO actual FROM housing.building_hawker;
    IF expected = 0 OR actual <> expected THEN
        RAISE EXCEPTION 'Spatial matrix incomplete: expected %, found %', expected, actual;
    END IF;
    IF EXISTS (
        SELECT FROM housing.building_hawker bh
        JOIN housing.hdb_building b USING (building_id)
        JOIN housing.hawker_centre h USING (hawker_id)
        WHERE b.latitude IS NULL OR h.latitude IS NULL
           OR abs(bh.distance_m - housing.haversine_m(b.latitude,b.longitude,h.latitude,h.longitude)) > 0.01
    ) THEN RAISE EXCEPTION 'Spatial row references unmatched location or distance differs by >0.01 m'; END IF;
    IF EXISTS (
        SELECT FROM housing.resale_transaction r JOIN housing.hdb_flat f USING (flat_id)
        WHERE r.lease_basis='estimated_years'
          AND r.remaining_lease_months <> 12*(99-(extract(year FROM r.sale_month)::integer-f.lease_commence_year))
    ) THEN RAISE EXCEPTION 'Estimated lease does not follow the declared year-resolution formula'; END IF;
END $$;

SELECT proximity_class, count(*) AS buildings FROM housing.nearest_hawker GROUP BY proximity_class;
SELECT proximity_class, count(*) AS buildings FROM housing.nearest_market_hawker GROUP BY proximity_class;
SELECT count(*) AS transactions, min(sale_month) AS first_month, max(sale_month) AS last_month
FROM housing.resale_transaction;
COMMIT;
