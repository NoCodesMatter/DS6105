"""Build the four HDB CSVs against the existing shared housing contract."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from core import ROOT, HDB_TABLES, code_sha256, contract, normalize, records, select_sources, sha256, write_json


def build(manifest, selectors, output, stage, root=ROOT):
    output = Path(output).resolve()
    if output.exists() or output.with_name(output.name + ".failed").exists():
        raise ValueError("Choose a new output directory; existing stages are never overwritten")
    sources = select_sources(manifest, selectors, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    towns, buildings, profiles = set(), {}, {}
    years_by_building = defaultdict(set)
    transformations, warnings, fatal = Counter(), Counter(), 0
    input_count, accepted, source_counts = 0, 0, []
    with tempfile.TemporaryDirectory(prefix=".hdb-stage-", dir=output.parent) as temp:
        work = Path(temp)
        with (work / "resale_transaction.csv").open("w", encoding="utf-8", newline="") as tx, \
             (work / "diagnostics.csv").open("w", encoding="utf-8", newline="") as df:
            tw = csv.writer(tx, lineterminator="\n")
            tw.writerow(contract.CSV_COLUMNS["resale_transaction"])
            dw = csv.writer(df, lineterminator="\n")
            dw.writerow(("source_dataset", "source_row", "severity", "issue", "source_record_json"))
            for source in sources:
                seen, source_accepted = 0, 0
                for ordinal, raw in records(source, root):
                    seen += 1
                    input_count += 1
                    try:
                        row, changes, issues = normalize(raw)
                        address = (row["block"], row["street_name"])
                        if address in buildings and buildings[address][1] != row["town"]:
                            raise ValueError(f"Address maps to multiple towns: {address}: {buildings[address][1]} / {row['town']}")
                        if address not in buildings:
                            bid = contract.building_id(*address)
                            buildings[address] = (bid, row["town"], *address, None, None)
                        bid = buildings[address][0]
                        key = (bid, row["flat_type"], row["storey_lower"], row["storey_upper"],
                               row["floor_area_sqm"], row["flat_model"], row["lease_commence_year"])
                        if key not in profiles:
                            profiles[key] = contract.flat_id(*key)
                        fid = profiles[key]
                        tid = contract.transaction_id(source["dataset_id"], ordinal)
                        tw.writerow((tid, fid, row["sale_month"], row["resale_price"],
                                     row["remaining_lease_months"], row["lease_basis"], source["dataset_id"], ordinal))
                    except (ValueError, KeyError, TypeError) as exc:
                        fatal += 1
                        dw.writerow((source["dataset_id"], ordinal, "error", str(exc), json.dumps(raw, ensure_ascii=False)))
                        continue
                    towns.add(row["town"])
                    years_by_building[bid].add(row["lease_commence_year"])
                    transformations.update(changes)
                    accepted += 1
                    source_accepted += 1
                    for issue in issues:
                        warnings[issue] += 1
                        dw.writerow((source["dataset_id"], ordinal, "warning", issue, json.dumps(raw, ensure_ascii=False)))
                source_counts.append({"dataset_id": source["dataset_id"], "input": seen, "accepted": source_accepted,
                                      "fatal_records": seen-source_accepted})
                print(f"Processed {source['label']}: {seen:,} input records", flush=True)
        report = {
            "status": "failed" if fatal else "ready_for_hdb_handoff", "stage": stage,
            "contract_version": contract.VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
            "sources": [{k: s[k] for k in ("dataset_id", "label", "path", "sha256", "source_url", "snapshot_utc", "rows")}
                        for s in sources],
            "source_counts": source_counts, "input_records": input_count, "accepted_records": accepted,
            "fatal_records": fatal, "dropped_records": 0 if not fatal else None,
            "transformations": dict(transformations), "warnings": dict(warnings),
            "building_coordinate_status": "All NULL pairs; awaiting Chen enrichment",
            "buildings_with_multiple_lease_years": [
                {"building_id": bid, "lease_commence_years": sorted(years)}
                for bid, years in sorted(years_by_building.items()) if len(years) > 1],
            "code_hash_mode": "utf8-lf-v1",
            "code_sha256": {p: code_sha256(ROOT / p) for p in (
                "db/schema/contract.py", "db/schema/001_schema.sql", "src/etl/hdb/core.py", "src/etl/hdb/pipeline.py")},
        }
        if fatal:
            failed = output.with_name(output.name + ".failed")
            failed.mkdir()
            (work / "diagnostics.csv").replace(failed / "diagnostics.csv")
            write_json(failed / "manifest.json", report)
            raise ValueError(f"Stage rejected: {fatal} invalid/conflicting records; diagnostics: {failed}")
        dimensions = {
            "town": ((t,) for t in sorted(towns)),
            "hdb_building": (buildings[a] for a in sorted(buildings)),
            "hdb_flat": ((profiles[k], *k) for k in sorted(profiles)),
        }
        for table, rows in dimensions.items():
            with (work / f"{table}.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(contract.CSV_COLUMNS[table])
                writer.writerows(rows)
        counts = {"town": len(towns), "hdb_building": len(buildings), "hdb_flat": len(profiles),
                  "resale_transaction": accepted}
        # Detect a theoretical ID collision before publishing a stage.
        if len({b[0] for b in buildings.values()}) != len(buildings) or len(set(profiles.values())) != len(profiles):
            raise ValueError("Entity ID collision; stage not published")
        if accepted != input_count or input_count != sum(s["rows"] for s in sources):
            raise ValueError("Source/output reconciliation failed")
        report["tables"] = {t: {"rows": counts[t], "sha256": sha256(work / f"{t}.csv"),
                               "bytes": (work / f"{t}.csv").stat().st_size} for t in HDB_TABLES}
        report["diagnostics_sha256"] = sha256(work / "diagnostics.csv")
        write_json(work / "manifest.json", report)
        # Same-filesystem rename publishes all CSVs and the manifest together.
        work.replace(output)
    print(json.dumps({"stage": stage, "tables": counts, "warnings": dict(warnings)}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/hdb_sources.json")
    parser.add_argument("--source", action="append", required=True, help="Dataset ID or label; repeat to build a cumulative stage")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.manifest, args.source, args.output, args.stage, args.root)
