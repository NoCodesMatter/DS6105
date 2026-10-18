# Proposal F-02: hawker inventory and coverage

**Status: PROPOSAL, not adopted.** Contract `1.0.0-draft.2` is unchanged by this document.
No crosswalk entry is approved, canonical identity is unchanged, and coverage rules are unchanged.
**Decision owners:** Chen (spatial data), LI (Q4/Q5 semantics). WU implements the DDL/contract
side after agreement.

**Inputs:** `hawker_geo.csv` (NTULearn), the frozen NEA snapshot (107 centres) and the unapproved
[candidate crosswalk](../verification/hawker_geo_validation_results.crosswalk.csv). The input files
were not modified.

## 1. Figures

| Figure | Value | Source / note |
|---|---|---|
| hawker_geo.csv records | 129 | hawker_geo.csv |
| NEA reference entities | 107 (81 with produce stalls > 0) | frozen API snapshot `47115c9e…` |
| Exact name + postcode | 17 | candidate crosswalk |
| Postcode-only, unique candidate | 87 | candidate crosswalk; **87/87 have identical block + street text** |
| Unresolved NEA centres | 3 | all three have **0 produce stalls** |
| Geo rows selected by no NEA entity | 25 | 129 − 104 |
| …of which with a blank address | **17**: every blank-address row is geo-only | analysis output |
| Ambiguous postcodes, shared postcodes, multiple claims | 0 | no many-to-many case in this snapshot |

### How far each geo-only centre is from the nearest matched NEA centre

These are centre-to-centre distances. They bound the problem; they do not measure it.

| Band | Count | Examples |
|---|---:|---|
| < 500 m (replacement/interim sites) | 5 | Chong Pang, Telok Blangah, Tanglin Halt, Bukit Timah Interim, Market Street |
| 500–1000 m | 2 | Margaret Drive, Our Tampines Hub |
| 1000–2000 m | 7 | Bukit Canberra, Yishun Park, Ci Yuan, Jurong West, Woodleigh Village, Bukit Batok West, Marsiling Mall |
| ≥ 2000 m (new estates) | 11 | Punggol Coast 6.7 km, Yew Tee 6.0 km, One Punggol 5.9 km, Senja 5.5 km, Bukit Panjang 4.3 km, Anchorvale 4.2 km, Fernvale 3.3 km, Pasir Ris Central 3.2 km, Buangkok 2.8 km, Kampung Admiralty 2.7 km, Tampines North 2.5 km |

**Interpretation.** Take a flat within 500 m of one of the 18 geo-only centres that are at
least 1 km from any NEA centre. Under the current inventory it cannot be classed `near`; its
class is computed against a centre one to several kilometres away. The bias is concentrated in
Punggol, Sengkang, Tampines North, Bukit Batok West, Tengah/Yew Tee and Yishun. Those estates
dominate 2017+ resale volume.

The number of affected **transactions** is BLOCKED: it needs HE's canonical buildings and
Chen's coordinates. Do not quote an estimate.

## 2. Answers to the analysis questions

### Q1. Which source should define canonical hawker identity?

The NEA list (`name_of_centre`, `location_of_centre`) for every centre it contains, as now.

- It is the prescribed attribute source.
- Every entity has a non-blank address.
- Names and addresses are unique in the snapshot.

The geo file has no persistent ID, and 17 of its rows have no address. It is a coordinate
source and alias evidence, not an identity source.

A geo-only centre needs a *documented secondary identity*, for example
`uuid5(["hawker", canonical geo NAME, canonical address or ""])` with `identity_source = 'geo'`.
That needs a contract change (Option B or C below).

### Q2. Should centres without a fresh-market stall count be stored?

Only if the team wants Q4 to use the real hawker landscape, which is this
proposal's recommendation. They must never be stored with count 0. A count of 0 asserts "no fresh market",
which the source does not say.

### Q3. How do we distinguish Unknown, Zero and Not Applicable?

| State | Meaning | Representation (Options B and C) |
|---|---|---|
| Reported zero | NEA lists the centre with 0 produce stalls | `market_produce_stalls = 0`, status `reported` |
| Reported positive | NEA count > 0 | value > 0, status `reported` |
| Unknown | Centre known only from the geo file | `market_produce_stalls IS NULL`, status `unknown` |
| Not applicable | Not observed: every NEA record has a count, and a centre type without a market concept would still be reported as 0 | not needed; do not invent a fourth state |

Eligibility for Q5 stays `market_produce_stalls > 0`. In SQL, `NULL > 0` is not true, so unknown
centres are **automatically excluded** from `nearest_market_hawker` without any view change. They
are reported separately as "unknown eligibility".

### Q4. How should NEA centres without coordinates be handled?

Keep them, with a NULL coordinate pair, as the contract already says. They have no IS NEAR pairs
and appear in `hawkers_without_coordinates`. The geo file has plausible successor sites for some
of them (for example Market Street Hawker Centre for Market Street Food Centre). A successor is a
**different place**, so its coordinates must not be assigned to the old entity without Chen's
explicit decision.

All three unresolved centres have 0 produce stalls, so they cannot change Q5. They can change Q4.

### Q5. Schema change, or ETL only?

- **Option A** is ETL-only.
- **Option B or C** needs a schema change. With the current DDL, a centre with an unknown count
  (NOT NULL) or no address (NOT NULL, part of the alternate key) cannot be stored.

Changing only the ETL cannot include the 17 blank-address geo centres. Making only the
stall count nullable is therefore **insufficient**: the address would also have to become
nullable or be replaced as an identity input.

### Q6. Effect on Q4/Q5 coverage

| | Q4 (nearest any centre) | Q5 (nearest fresh-market centre) |
|---|---|---|
| Option A | Biased toward farther classes in new estates; bias size BLOCKED | Uses the 81 NEA centres with produce stalls. Any geo-only centre that has a market is invisible (unknown). |
| Option B/C | Uses up to 129 centre locations | Unchanged set (known > 0); unknown-eligibility centres are reported, not guessed |

### Q7. Effect on Task 2 and interfaces

- **Chen:** produces `hawker_centre.csv`. Options B/C add columns (B) or a file (C), plus
  geo-only rows and the distance pairs for them.
- **Sun:** loads one extra CSV (C only).
- **LI:**
  - Q5 needs no change under B (NULL > 0 is false).
  - Q6 must join seven tables under C.
- **HE:** not affected.
- **Matrix:** about 24% more distance rows if all 25 centres get coordinates
  (129 vs 104 geocoded centres).

## 3. Options

| | A. NEA-only inventory (status quo) | B. Single table with explicit unknowns | C. Split location from NEA attributes |
|---|---|---|---|
| Change | None. Document the coverage loss. | `market_produce_stalls` NULL allowed + `stall_count_status`, `identity_source`. `address` nullable, uniqueness `UNIQUE NULLS NOT DISTINCT (centre_name, address)` (PG15+). CHECK linking status to nullness. | `hawker_centre(hawker_id, centre_name, address NULL, location)` + new `hawker_market_profile(hawker_id PK/FK, market_produce_stalls NOT NULL)` 1:(0,1) |
| Data integrity | High (no NULL counts), but the inventory is knowingly incomplete | High if the status CHECK is enforced; NULLs are explicit | Highest: absence of a profile row means unknown, so no NULL count exists |
| Modelling accuracy | Low for Q4 in post-2016 estates | Good | Best (separates existence from NEA attributes) |
| SQL compatibility | Unchanged | Views unchanged; queries unchanged | Views must join the profile table; Q6 needs 7 tables |
| Cost | ~0.5 h documentation | ~0.5 day (DDL, contract, ER update) | ~1 day plus more ETL work for Chen |
| Team impact | None now; risk at the viva | Chen: 2 columns + new rows; LI: none | Chen + Sun + LI all change |
| Normalisation | BCNF | BCNF (the status is not determined by any non-key attribute) | BCNF |

### Recommendation

**Option B, if Chen and LI agree that Q4 should reflect current hawker locations. Otherwise
Option A, with the limitation quantified in the report.**

B gives most of C's accuracy at half the cost and keeps every existing query and view working.

**In either case, independent of the option:** approve the 104 matched centres after Chen's
spot-check. The evidence supports it (87/87 identical block + street text, no ambiguity), but
the approval itself is Chen's.

**Temporal caveat (all options).** Many geo-only centres opened after 2016. Option B classifies
1990s sales against centres that did not exist then. The team must choose between:
- (i) one static current inventory, documented as a limitation; or
- (ii) adding opening years, which is new data not in the prescribed sources and needs
  coordinator approval.

This proposal suggests (i).

## 4. What is needed to adopt Option B (not done)

1. Chen/LI decision recorded in `design_decisions.md`.
2. DDL:
   - nullable `market_produce_stalls`, `address`;
   - `stall_count_status text NOT NULL CHECK (...)`;
   - `identity_source text NOT NULL CHECK (identity_source IN ('nea','geo'))`;
   - `UNIQUE NULLS NOT DISTINCT (centre_name, address)`;
   - CHECK `(stall_count_status='reported') = (market_produce_stalls IS NOT NULL)`.
3. Contract `1.1.0` (CSV header change for `hawker_centre.csv`). Update the conceptual
   ER and logical schema diagrams.
4. Checks for the change:
   - unknown count excluded from `nearest_market_hawker`;
   - zero and unknown are distinguishable;
   - geo-only identity is stable.
