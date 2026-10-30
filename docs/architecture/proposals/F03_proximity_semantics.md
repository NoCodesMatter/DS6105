# Decision F-03: proximity semantics and maximum effective distance

**Status: DECIDED at Gate 0 (2026-10-30): Option B with D_max = 2,000 m.** Agreed by Chen,
LI and WU, and implemented in contract `1.0.0`.

- **Classes:** near [0, 500) m, medium [500, 1000) m, far [1000, 2000] m.
- **Beyond 2,000 m:** no proximity level; `housing.proximity_class` returns NULL.

The analysis below is kept as the decision record.

**Evidence used for the decision:**
- **Chen, real data:** the 500/1000 m thresholds hold. The nearest fresh-market distance has
  p95 = 5.1–5.3 km, so the rule "p95, capped at 2,000 m" gives 2,000 m. About 29% of
  transactions across the five files get no class.
- **LI, Stage 1, frozen `sql/queries/`, no code change:**

  | Query | Rows without cap | Rows with cap |
  |---|---:|---:|
  | Q4 | 45 | 43 |
  | Q5 | 24 | 22 |
  | Q6 | 60 | 55 |

  Q5 still keeps 8 towns above the SGD 450k budget. Q4 compares only `near`/`far`, and Q5
  excludes NULL classes.

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
| Nearest centre beyond D_max | Class NULL ("beyond"). Excluded from Q4 near/far averages and Q5. Counted by `buildings_nearest_hawker_beyond_2000m` and `buildings_nearest_market_beyond_2000m` in `validate_loaded_data.sql`. |
| No fresh-market centre geocoded | No `nearest_market_hawker` row (existing behaviour) |
| Distance exactly 500 / 1000 / D_max | Half-open intervals; D_max is the inclusive upper limit of far. |
| Ties | Unchanged: smallest hawker_id wins; the class does not depend on the tie |
| Implausible coordinates (outside Singapore) | Chen's ETL flags them before the matrix is built; the DDL still forbids (0,0) and NaN/∞ |

## 6. Impact of adopting Option B (implemented in 1.0.0)

| Layer | Change |
|---|---|
| ER diagrams | `proximity_level` rule text becomes "near [0,500) \| medium [500,1000) \| far [1000, D_max]; beyond D_max → no level". The IS NEAR relationship and its (0,N)/(0,N) participations are unchanged. |
| DDL | `proximity_class` returns NULL above 2,000 m. The nearest views keep NULL classes visible, so coverage can be counted; queries filter them. In the same release, the views compute the class after `DISTINCT ON` (Lu's rewrite: identical rows, faster). |
| CSV / ETL | None for the full-matrix contract. Optionally Chen may prune pairs beyond D_max (that **is** a CSV/matrix contract change and would need the completeness check in `validate_loaded_data.sql` rewritten). Not recommended now. |
| Queries (LI) | Already in LI's frozen SQL: Q4 `WHERE proximity_class IN ('near','far')`; Q5 `WHERE proximity_class IS NOT NULL`. Report beyond-2,000 m counts. |
| Task 3/4 | No change in table sizes. The database must be rebuilt with 1.0.0 before official Task 3 timing. |

## 7. Data dependency (resolved by Chen's real-data check)

Resolved: Chen ran the analysis below on the canonical geocoded buildings and the approved
inventory. Result: 500/1000 m kept; nearest fresh-market p95 = 5.1–5.3 km, so D_max = 2,000 m.
Method used, for every canonical building:

1. compute the distance to its nearest centre and to its nearest fresh-market centre;
2. report the percentiles (p50, p75, p90, p95, p99, max) of both distributions;
3. report the class occupancy under the current contract and under the bounded proposal;
4. choose D_max from the fresh-market distribution, and freeze it before any Task 3 timing.
