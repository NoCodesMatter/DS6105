-- =============================================================================
-- SD6103 / SD6105 Data Systems Project — Query 2 (Q2)
-- Module Owner: LI JIAHANG — SQL Query & Business Analysis Owner
-- Target Schema: housing (Contract 1.0.0-draft.2, PostgreSQL 15+)
--
-- Appendix A & Schema Contract Requirement:
--   Categorize sales transactions into remaining lease buckets using CASE
--   expressions, then compute the median resale price, average price per square
--   meter, and total transaction volume for each bucket per town.
--
-- Lease Buckets:
--   - '< 50 years'  : remaining_lease_months < 600
--   - '50 - 70 years': remaining_lease_months BETWEEN 600 AND 840 (inclusive)
--   - '> 70 years'  : remaining_lease_months > 840
--   - 'unknown'     : remaining_lease_months IS NULL (retains the 51 historical
--                     pre-commencement transactions where lease_basis = 'unknown')
--
-- Median Computation:
--   Computed exactly via PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resale_price).
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

