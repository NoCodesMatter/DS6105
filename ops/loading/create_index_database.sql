-- Run once against postgres after the complete Task 3 baseline is accepted.
-- Creates a separate full-size copy for Task 4; existing databases are never reset.
\set ON_ERROR_STOP on
\connect sd6105_stage5
DO $$ BEGIN
    IF (SELECT count(*) FROM housing.resale_transaction) <> 989158 THEN
        RAISE EXCEPTION 'Source is not the accepted full-size stage';
    END IF;
    IF EXISTS (
        SELECT FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        LEFT JOIN pg_constraint c ON c.conindid=i.indexrelid
        WHERE n.nspname='housing' AND c.oid IS NULL
    ) THEN
        RAISE EXCEPTION 'Source contains optional indexes; expected the clean baseline';
    END IF;
END $$;
\connect postgres
CREATE DATABASE sd6105_stage5_indexed TEMPLATE sd6105_stage5;
\connect sd6105_stage5_indexed
SELECT current_database() AS database, count(*) AS transactions
FROM housing.resale_transaction;
