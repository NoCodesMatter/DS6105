# Architecture documentation (Task 1)

Start with the **[handover summary](completion_report.md)**. It says what is final, what is still a
draft or proposal, and what each member needs next.

| Document | Content | Status |
|---|---|---|
| [Task 1 report](task1_report.md) | Report-ready section: assumptions, conceptual ER, proximity definition, logical schema and mapping, normalisation, constraints, full creation SQL | Draft text for Lu's final report |
| [Conceptual ER](conceptual_er.png) ([draw.io](conceptual_er.drawio), [SVG](conceptual_er.svg)) | Chen notation with identifiers, (min,max) participation and the IS NEAR proximity relationship | Matches DDL 1.0.0-draft.2 |
| [Logical schema](er_diagram.png) ([draw.io](er_diagram.drawio), [SVG](er_diagram.svg)) | Six tables, keys, foreign keys, mapping of the ER (file name kept for link stability) | Matches DDL 1.0.0-draft.2 |
| [Schema contract](schema_contract.md) | Exact CSV headers and types, null rules, ID serialisation, load order, change log | **Draft**: binding for development, not frozen until Gate 0 |
| [Design decisions](design_decisions.md) | Flat identity, dependency analysis (3NF / BCNF), distance matrix, proximity classes, constraints, open decisions | Proposal for team review |
| [Architecture overview](architecture_overview.png) ([draw.io](architecture_overview.drawio), [SVG](architecture_overview.svg)) | Module hand-offs between members | Reference |
| [Proposal F-02](proposals/F02_hawker_coverage.md) | Hawker inventory and coverage options | **PROPOSAL, not adopted.** Chen/LI to decide |
| [Proposal F-03](proposals/F03_proximity_semantics.md) | Bounded third proximity class / maximum effective distance | **PROPOSAL, not adopted.** Chen/LI to decide |
| [Candidate crosswalk](verification/hawker_geo_validation_results.crosswalk.csv) | 107 NEA centres → hawker_geo.csv rows (17 exact, 87 postcode-only, 3 unmatched) | **Unapproved.** Chen to review |

The SQL and the Python ID helper are in [db/schema/](../../db/schema/README.md).
