-- Supporting records for the three probes in db/schema/validate_loaded_data.sql.
-- Run after loading all five frozen HDB sources and Chen's spatial outputs.
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH multiple_lease_years AS (
    SELECT b.building_id, b.block, b.street_name, b.town_name,
           array_agg(DISTINCT f.lease_commence_year ORDER BY f.lease_commence_year) AS lease_years
    FROM housing.hdb_building b
    JOIN housing.hdb_flat f USING (building_id)
    GROUP BY b.building_id, b.block, b.street_name, b.town_name
    HAVING count(DISTINCT f.lease_commence_year) > 1
), shared_coordinate_pairs AS (
    SELECT latitude, longitude, count(*) AS buildings,
           array_agg(building_id ORDER BY building_id) AS building_ids
    FROM housing.hdb_building
    WHERE latitude IS NOT NULL
    GROUP BY latitude, longitude
    HAVING count(*) > 1
), pre_commencement AS (
    SELECT r.source_dataset, count(*) AS transactions,
           count(*) FILTER (WHERE r.lease_basis = 'unknown'
                            AND r.remaining_lease_months IS NULL) AS unknown_lease_transactions
    FROM housing.resale_transaction r
    JOIN housing.hdb_flat f USING (flat_id)
    WHERE extract(year FROM r.sale_month) < f.lease_commence_year
    GROUP BY r.source_dataset
), source_counts AS (
    SELECT source_dataset, count(*) AS transactions,
           min(sale_month) AS first_month, max(sale_month) AS last_month
    FROM housing.resale_transaction
    GROUP BY source_dataset
)
SELECT json_build_object(
    'table_counts', json_build_object(
        'town', (SELECT count(*) FROM housing.town),
        'hdb_building', (SELECT count(*) FROM housing.hdb_building),
        'hdb_flat', (SELECT count(*) FROM housing.hdb_flat),
        'resale_transaction', (SELECT count(*) FROM housing.resale_transaction),
        'hawker_centre', (SELECT count(*) FROM housing.hawker_centre),
        'building_hawker', (SELECT count(*) FROM housing.building_hawker)),
    'source_counts', (SELECT json_agg(s ORDER BY source_dataset) FROM source_counts s),
    'coordinate_coverage', json_build_object(
        'buildings_with_coordinates', (SELECT count(*) FROM housing.hdb_building WHERE latitude IS NOT NULL),
        'buildings_without_coordinates', (SELECT count(*) FROM housing.hdb_building WHERE latitude IS NULL),
        'hawkers_with_coordinates', (SELECT count(*) FROM housing.hawker_centre WHERE latitude IS NOT NULL),
        'hawkers_without_coordinates', (SELECT count(*) FROM housing.hawker_centre WHERE latitude IS NULL)),
    'buildings_with_multiple_lease_years',
        COALESCE((SELECT json_agg(m ORDER BY block, street_name) FROM multiple_lease_years m), '[]'::json),
    'coordinate_pairs_shared_by_buildings',
        COALESCE((SELECT json_agg(c ORDER BY latitude, longitude) FROM shared_coordinate_pairs c), '[]'::json),
    'transactions_before_lease_commencement_by_source',
        COALESCE((SELECT json_agg(p ORDER BY source_dataset) FROM pre_commencement p), '[]'::json),
    'proximity_boundary_checks', json_build_object(
        'at_0m', housing.proximity_class(0),
        'at_500m', housing.proximity_class(500),
        'at_1000m', housing.proximity_class(1000),
        'at_2000m', housing.proximity_class(2000),
        'above_2000m', housing.proximity_class(2000.001))
);
COMMIT;
