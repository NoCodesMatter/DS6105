# Proposal F-03: proximity semantics and maximum effective distance

**Status: PROPOSAL, not adopted.** The formal contract stays as `1.0.0-draft.2`:
near [0, 500) m, medium [500, 1000) m, far [1000 m, ∞). `housing.proximity_class` is unchanged.
**Decision owners:** Chen (spatial data, thresholds), LI (Q4/Q5 SQL). WU updates the contract,
function and ER diagrams after agreement.

## 1. What the brief requires

- **p.3:** three *distinct* levels of proximity, defined by the team and modelled in the ER.
  Distance-based definitions are explicitly allowed.
- **Q4 (p.7):** "price differential between HDB flats of **closest proximity class** and HDB flats
  in the **furthest proximity class** you defined". Output: `town, flat_type, avg_price_near_hawker,
  avg_price_far_hawker, price_diff_percentage`.
- **Q5 (p.7):** for all towns, the average resale price **per proximity class** "for flats that
  are **in proximity to** a hawker with fresh market stalls", then a budget filter that keeps some
  but not all towns.

The brief does **not** require a maximum distance. An unbounded third level is therefore not a
rule violation. The question is whether it gives Q5's phrase "in proximity to" a defensible meaning.

## 2. Assessment of the current definition

| Check | Result |
|---|---|
| Three distinct, mutually exclusive, exhaustive levels | Yes. Half-open intervals give every non-negative distance exactly one class. |
| Q4 meaning | **Adequate.** Each building gets the class of its nearest geocoded centre; near and far are compared. An unbounded far class does not distort Q4. It only means "far" = "nearest centre ≥ 1 km". |
| Q5 meaning | **Weak.** Restricting the nearest centre to fresh-market centres is meaningful: it changes which centre, and so which class, a flat gets. But no flat is ever *excluded* as "not in proximity". For example, a building 24 km from every fresh-market centre is still classed `far`. The phrase "in proximity to" adds nothing beyond "a fresh-market centre exists somewhere". |
| Thresholds validated on real distances | **No: BLOCKED.** Canonical geocoded HDB buildings do not exist yet. 500/1000 m are interpretable walking-scale choices, not data-derived cut-points. |

## 3. Three different "proximity" meanings

They must not be mixed in one query.

| Meaning | Definition | Classes per sale | Use |
|---|---|---|---|
| Nearest hawker | Class of the minimum-distance centre (`nearest_hawker`) | Exactly 1 (or none if ungeocoded) | **Q4.** "Flats of the closest class" needs one class per flat. |
| Nearest fresh-market hawker | Same, over centres with produce stalls > 0 (`nearest_market_hawker`) | Exactly 1 (or none) | **Q5.** "In proximity to a hawker with fresh market stalls". |
| Any hawker | Every IS NEAR pair within a class | 0..H per class; one flat can be near A and far B | **Not suitable for Q4/Q5.** Each sale would be counted in several classes and prices weighted by centre count. Usable only for per-centre analyses (e.g. a possible Q6), with explicit de-duplication. |

The current views implement the first two correctly. They give different centres when the
nearest centre has no market, and neither multiplies transactions.

## 4. Options

| | A. Keep [1000, ∞) and justify it | B. Bounded far + maximum effective distance (recommended) | C. Data-driven tertiles |
|---|---|---|---|
| Definition | near < 500, medium < 1000, far ≥ 1000 | near [0,500), medium [500,1000), far [1000, D_max]. Beyond D_max: **no proximity relationship** (class NULL, reported as coverage). | Cut-points at the 33rd/67th percentiles of the nearest-distance distribution |
| Q5 "in proximity" | Vacuous | Meaningful: flats beyond D_max of any fresh-market centre are excluded and counted | Meaningful only if a cap is also added |
| Interpretability | High | High | Low (thresholds change with the data stage; hard to explain at the viva) |
| Stability across the 5 stages | Stable | Stable if D_max is fixed once | Unstable unless frozen on stage 5 |
| Change size | None (text only) | One line in `proximity_class` + contract/ER. **No CSV or table change** if the full matrix is kept. | Same as B, plus a calibration step |

**Recommendation: Option B.**

- Keep 500 and 1000 m.
- Set D_max from the real nearest-fresh-market distance distribution: the smallest round value
  ≥ the 95th percentile, capped at 2000 m, where 2000 m is a ~25-minute walk. The cap is a
  candidate pending real data, not a validated value.
- Freeze D_max on stage 5 (or all five stages) before any Task 3 timing.

## 5. Outliers and edge cases under Option B

| Case | Handling |
|---|---|
| Building without coordinates | No IS NEAR pairs → no class. Counted in `transactions_without_spatial_coverage`. |
| Nearest centre beyond D_max | Class NULL ("beyond"). Excluded from Q4 near/far averages and Q5. Counted in a new diagnostic `buildings_beyond_max_effective_distance`. |
| No fresh-market centre geocoded | No `nearest_market_hawker` row (existing behaviour) |
| Distance exactly 500 / 1000 / D_max | Half-open intervals; D_max is the inclusive upper limit of far. |
| Ties | Unchanged: smallest hawker_id wins; the class does not depend on the tie |
| Implausible coordinates (outside Singapore) | Chen's ETL flags them before the matrix is built; the DDL still forbids (0,0) and NaN/∞ |

## 6. Impact if Option B is adopted

| Layer | Change |
|---|---|
| ER diagrams | `proximity_level` rule text becomes "near [0,500) \| medium [500,1000) \| far [1000, D_max]; beyond D_max → no level". The IS NEAR relationship and its (0,N)/(0,N) participations are unchanged. |
| DDL | `proximity_class`: `WHEN distance_m <= D_max THEN 'far' ELSE NULL`. Views unchanged (NULL class propagates). Optionally `nearest_*` could skip NULL classes; recommendation: keep the views and filter in queries, so coverage stays visible. |
| CSV / ETL | None for the full-matrix contract. Optionally Chen may prune pairs beyond D_max (that **is** a CSV/matrix contract change and would need the completeness check in `validate_loaded_data.sql` rewritten). Not recommended now. |
| Queries (LI) | Q4: `WHERE proximity_class IN ('near','far')` (unchanged in effect). Q5: add `proximity_class IS NOT NULL`, which now has meaning. Report beyond-D_max counts. |
| Task 3/4 | No change in table sizes; runtime unchanged (the function is evaluated after the sort). |

## 7. Data dependency (explicit)

No threshold here is validated. Validation needs canonical HDB buildings (HE) with hdb.csv
coordinates (Chen) and the approved hawker inventory (F-02). Then, for every canonical building:

1. compute the distance to its nearest centre and to its nearest fresh-market centre;
2. report the percentiles (p50, p75, p90, p95, p99, max) of both distributions;
3. report the class occupancy under the current contract and under the bounded proposal;
4. choose D_max from the fresh-market distribution, and freeze it before any Task 3 timing.
