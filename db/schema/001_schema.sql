-- Contract 1.0.0-draft.2. PostgreSQL 15+. Intentionally fails if housing exists.
-- No extensions, seed data, optional indexes, destructive reset, or ETL required.
BEGIN;
CREATE SCHEMA housing;
COMMENT ON SCHEMA housing IS 'Housing schema contract 1.0.0-draft.2; team review pending';

CREATE DOMAIN housing.canonical_text AS text
    CHECK (VALUE = upper(VALUE)
           AND VALUE ~ '^[^[:space:]]+( [^[:space:]]+)*$');

CREATE TABLE housing.town (
    town_name housing.canonical_text PRIMARY KEY
);

CREATE TABLE housing.hdb_building (
    building_id uuid PRIMARY KEY,
    town_name housing.canonical_text NOT NULL REFERENCES housing.town ON DELETE RESTRICT,
    block housing.canonical_text NOT NULL,
    street_name housing.canonical_text NOT NULL,
    latitude double precision,
    longitude double precision,
    CONSTRAINT building_address_key UNIQUE (block, street_name),
    CONSTRAINT building_coordinate_pair CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CONSTRAINT building_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT building_longitude CHECK (longitude BETWEEN -180 AND 180),
    -- Contract: no zero-coordinate sentinels; unknown location is NULL, not (0,0).
    CONSTRAINT building_not_zero_sentinel CHECK (NOT (latitude = 0 AND longitude = 0))
);

CREATE TABLE housing.hdb_flat (
    flat_id uuid PRIMARY KEY,
    building_id uuid NOT NULL REFERENCES housing.hdb_building ON DELETE RESTRICT,
    flat_type housing.canonical_text NOT NULL,
    storey_lower smallint NOT NULL,
    storey_upper smallint NOT NULL,
    floor_area_sqm numeric(8,2) NOT NULL,
    flat_model housing.canonical_text NOT NULL,
    lease_commence_year smallint NOT NULL,
    CONSTRAINT flat_type_values CHECK (flat_type IN
        ('1 ROOM','2 ROOM','3 ROOM','4 ROOM','5 ROOM','EXECUTIVE','MULTI GENERATION')),
    CONSTRAINT flat_storey_bounds CHECK (storey_lower > 0 AND storey_upper >= storey_lower),
    CONSTRAINT flat_positive_area CHECK (floor_area_sqm > 0 AND floor_area_sqm < 'Infinity'::numeric),
    CONSTRAINT flat_lease_year CHECK (lease_commence_year BETWEEN 1 AND 9999),
    CONSTRAINT flat_profile_key UNIQUE
        (building_id, flat_type, storey_lower, storey_upper, floor_area_sqm,
         flat_model, lease_commence_year)
);
COMMENT ON TABLE housing.hdb_flat IS
    'Observed flat profile, not an identified physical dwelling. Never infer repeat sales.';

CREATE TABLE housing.resale_transaction (
    transaction_id uuid PRIMARY KEY,
    flat_id uuid NOT NULL REFERENCES housing.hdb_flat ON DELETE RESTRICT,
    sale_month date NOT NULL,
    resale_price numeric(14,2) NOT NULL,
    remaining_lease_months smallint,
    lease_basis text NOT NULL,
    source_dataset text NOT NULL,
    source_row integer NOT NULL,
    CONSTRAINT transaction_month CHECK
        (sale_month BETWEEN DATE '0001-01-01' AND DATE '9999-12-01'
         AND extract(day FROM sale_month) = 1),
    CONSTRAINT transaction_positive_price CHECK
        (resale_price > 0 AND resale_price < 'Infinity'::numeric),
    CONSTRAINT transaction_lease_range CHECK (remaining_lease_months BETWEEN 0 AND 1188),
    CONSTRAINT transaction_lease_basis CHECK (
        (lease_basis = 'unknown' AND remaining_lease_months IS NULL)
        OR (lease_basis = 'reported_months' AND remaining_lease_months IS NOT NULL)
        OR (lease_basis IN ('reported_years','estimated_years')
            AND remaining_lease_months IS NOT NULL AND remaining_lease_months % 12 = 0)),
    CONSTRAINT transaction_source_dataset CHECK (source_dataset ~ '^d_[0-9a-f]{32}$'),
    CONSTRAINT transaction_source_row CHECK (source_row > 0),
    CONSTRAINT transaction_source_key UNIQUE (source_dataset, source_row)
);
COMMENT ON COLUMN housing.resale_transaction.sale_month IS
    'First of source month: approval before March 2012, registration thereafter.';
COMMENT ON COLUMN housing.resale_transaction.remaining_lease_months IS
    'At source transaction/application time; whole-year reports/estimates retain their basis.';

CREATE TABLE housing.hawker_centre (
    hawker_id uuid PRIMARY KEY,
    centre_name housing.canonical_text NOT NULL,
    address housing.canonical_text NOT NULL,
    market_produce_stalls integer NOT NULL,
    latitude double precision,
    longitude double precision,
    CONSTRAINT hawker_name_address_key UNIQUE (centre_name, address),
    CONSTRAINT hawker_market_stalls CHECK (market_produce_stalls >= 0),
    CONSTRAINT hawker_coordinate_pair CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CONSTRAINT hawker_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT hawker_longitude CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT hawker_not_zero_sentinel CHECK (NOT (latitude = 0 AND longitude = 0))
);

CREATE TABLE housing.building_hawker (
    building_id uuid NOT NULL REFERENCES housing.hdb_building ON DELETE RESTRICT,
    hawker_id uuid NOT NULL REFERENCES housing.hawker_centre ON DELETE RESTRICT,
    distance_m double precision NOT NULL,
    PRIMARY KEY (building_id, hawker_id),
    -- Half Earth's circumference (R=6371008.8 m), rounded UP to a safe upper bound.
    CONSTRAINT building_hawker_distance CHECK (distance_m BETWEEN 0 AND 20015115)
);
COMMENT ON TABLE housing.building_hawker IS
    'Complete geocoded-building x geocoded-prescribed-hawker matrix per frozen snapshot.';

CREATE FUNCTION housing.proximity_class(distance_m double precision)
RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT CASE WHEN distance_m < 0 OR distance_m > 20015115 THEN NULL
                WHEN distance_m < 500 THEN 'near'
                WHEN distance_m < 1000 THEN 'medium'
                ELSE 'far' END
$$;

CREATE FUNCTION housing.haversine_m(lat1 double precision, lon1 double precision,
                                    lat2 double precision, lon2 double precision)
RETURNS double precision LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT 2 * 6371008.8 * asin(sqrt(least(1.0, greatest(0.0,
        power(sin(radians(lat2-lat1)/2), 2)
        + cos(radians(lat1))*cos(radians(lat2))
          * power(sin(radians(lon2-lon1)/2), 2)))))
$$;

-- Derived attributes live in views: no distance -> class or stalls -> boolean
-- transitive dependencies in stored base tables. Views have no import CSVs.
CREATE VIEW housing.building_hawker_proximity AS
SELECT building_id, hawker_id, distance_m, housing.proximity_class(distance_m) AS proximity_class
FROM housing.building_hawker;

CREATE VIEW housing.nearest_hawker AS
SELECT DISTINCT ON (building_id)
    building_id, hawker_id, distance_m, housing.proximity_class(distance_m) AS proximity_class
FROM housing.building_hawker
ORDER BY building_id, distance_m, hawker_id;

CREATE VIEW housing.nearest_market_hawker AS
SELECT DISTINCT ON (bh.building_id)
    bh.building_id, bh.hawker_id, bh.distance_m,
    housing.proximity_class(bh.distance_m) AS proximity_class
FROM housing.building_hawker AS bh
JOIN housing.hawker_centre AS h USING (hawker_id)
WHERE h.market_produce_stalls > 0
ORDER BY bh.building_id, bh.distance_m, bh.hawker_id;
COMMIT;
