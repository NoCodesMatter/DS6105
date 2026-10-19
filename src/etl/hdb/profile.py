"""Inspect every source record, including cross-file assumptions, before building."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from core import ROOT, contract, normalize, records, select_sources, write_json

EVIDENCE_FILES = ("source_issues.csv", "profile.md", "profile.json")


def _profile_into(manifest, output, root=ROOT):
    sources = select_sources(manifest, root=root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results, towns_by_address, leases_by_address = [], defaultdict(set), defaultdict(set)
    lease_witnesses = {}
    with (output / "source_issues.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("dataset_id", "source_row", "severity", "issue", "source_record_json"))
        for source in sources:
            count, valid, duplicate_excess = 0, 0, 0
            missing, types, models, storeys, leases, changes, issues = (Counter() for _ in range(7))
            months, towns, signatures = set(), set(), set()
            bounds = {}
            for ordinal, raw in records(source, root):
                count += 1
                raw_json = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
                signature = hashlib.sha256(raw_json.encode()).digest()
                if signature in signatures:
                    duplicate_excess += 1
                signatures.add(signature)
                missing.update(k for k, v in raw.items() if not v.strip())
                types[raw["flat_type"]] += 1
                models[raw["flat_model"]] += 1
                storeys[raw["storey_range"]] += 1
                try:
                    row, conversions, warnings = normalize(raw)
                except (ValueError, KeyError, TypeError) as exc:
                    issues["fatal_invalid_record"] += 1
                    writer.writerow((source["dataset_id"], ordinal, "error", str(exc), raw_json))
                    continue
                valid += 1
                changes.update(conversions)
                months.add(row["sale_month"][:7])
                towns.add(row["town"])
                leases[row["lease_basis"]] += 1
                for key in ("floor_area_sqm", "resale_price", "lease_commence_year", "storey_lower", "storey_upper"):
                    value = Decimal(str(row[key]))
                    low, high = bounds.get(key, (value, value))
                    bounds[key] = (min(low, value), max(high, value))
                address = (row["block"], row["street_name"])
                towns_by_address[address].add(row["town"])
                leases_by_address[address].add(row["lease_commence_year"])
                witness_key = (*address, row["lease_commence_year"])
                if witness_key not in lease_witnesses:
                    lease_witnesses[witness_key] = {"dataset_id": source["dataset_id"], "source_row": ordinal,
                                                    "source_record": raw}
                for issue in warnings:
                    issues[issue] += 1
                    writer.writerow((source["dataset_id"], ordinal, "warning", issue, raw_json))
            result = {
                "dataset_id": source["dataset_id"], "label": source["label"], "sha256": source["sha256"],
                "rows": count, "normalizable_rows": valid, "header": source["header"],
                "month_min": min(months) if months else None, "month_max": max(months) if months else None,
                "month_count": len(months), "towns": sorted(towns), "missing_values": dict(missing),
                "raw_flat_types": dict(types), "raw_flat_models": dict(models), "raw_storey_ranges": dict(storeys),
                "lease_basis_counts": dict(leases), "transformations": dict(changes), "issues": dict(issues),
                "identical_raw_records_sha256_excess": duplicate_excess,
                "bounds": {k: {"min": str(v[0]), "max": str(v[1])} for k, v in bounds.items()},
            }
            results.append(result)
            print(f"Profiled {source['label']}: {count:,} rows, {count-valid} fatal, {duplicate_excess:,} equal-looking rows retained", flush=True)
    conflicts = [{"block": b, "street_name": s, "towns": sorted(t)}
                 for (b, s), t in sorted(towns_by_address.items()) if len(t) > 1]
    lease_variants = [{"block": b, "street_name": s, "lease_commence_years": sorted(y),
                       "source_examples": [lease_witnesses[(b, s, year)] for year in sorted(y)]}
                      for (b, s), y in sorted(leases_by_address.items()) if len(y) > 1]
    results.sort(key=lambda s: s["month_min"] or "")
    report = {"contract_version": contract.VERSION, "sources": results,
              "total_source_records": sum(s["rows"] for s in results),
              "address_town_conflicts": conflicts, "buildings_with_multiple_lease_years": lease_variants,
              "distinct_canonical_addresses": len(towns_by_address),
              "coordinate_dependency_checked": False}
    write_json(output / "profile.json", report)
    lines = ["# HDB source profiling", "", f"Contract: `{contract.VERSION}`. All source records inspected; no sampling.", "",
             "Source hashes, URLs and acquisition times are in `data/manifests/hdb_sources.json`.", "",
             "| Source | Observed months | Records | Lease bases | Fatal records | Equal-looking excess records (preserved) |",
             "|---|---|---:|---|---:|---:|"]
    for s in results:
        lines.append(f"| {s['label']} | {s['month_min']} to {s['month_max']} | {s['rows']:,} | {s['lease_basis_counts']} | {s['rows']-s['normalizable_rows']} | {s['identical_raw_records_sha256_excess']:,} |")
    lines += ["", "## Cross-file checks", "",
              f"- Distinct canonical addresses: {len(towns_by_address):,}.",
              f"- Addresses assigned to multiple towns: **{len(conflicts)}**. Any selected stage containing these conflicts must fail until HE/WU agree a correction or contract revision.",
              f"- Buildings with multiple lease commencement years: **{len(lease_variants)}**. This is reported evidence, not grounds to remove records.",
              "- Coordinate uniqueness is outside this module; building coordinates are supplied by Chen.",
              "", "## Interpretation", "",
              "Older files without a remaining_lease column use the contract's year-resolution estimate. Missing or invalid values in a present remaining_lease column remain unknown and are diagnosed.",
              "Numeric year values and text years/months retain their distinct lease_basis. Storey bins are preserved. Historical MULTI-GENERATION is explicitly mapped to MULTI GENERATION.",
              "Equal-looking rows are counted using complete raw-record SHA-256 signatures, but are never removed: each source record retains its own transaction identity.",
              "All field ranges, source categories, transformations and cross-file counterexamples are in profile.json. Source-level errors and warnings with original row numbers are in source_issues.csv.",
              "The 2017-onwards file is a changing public dataset: reuse the frozen bytes and hash for experiments, not a fresh live download."]
    (output / "profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def profile(manifest, output, root=ROOT):
    """Prepare all evidence before replacing an existing report.

    Parsing/generation failures leave previous evidence untouched. Publication is
    a short series of file renames with rollback on ordinary I/O failures; it is
    not a transaction for concurrent readers or abrupt process termination.
    Other evidence files in the destination directory are preserved.
    """
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hdb-profile-", dir=output.parent) as temp:
        work = Path(temp)
        generated = work / "generated"
        report = _profile_into(manifest, generated, root)
        backup = work / "previous"
        backup.mkdir()
        for name in EVIDENCE_FILES:
            if (output / name).exists():
                shutil.copy2(output / name, backup / name)
        output.mkdir(exist_ok=True)
        published = []
        try:
            for name in EVIDENCE_FILES:
                (generated / name).replace(output / name)
                published.append(name)
        except OSError:
            for name in reversed(published):
                previous = backup / name
                if previous.exists():
                    previous.replace(output / name)
                else:
                    (output / name).unlink()
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest or root / "data/manifests/hdb_sources.json"
    output = args.output or (Path(__file__).parent / "evidence" if root == ROOT.resolve()
                             else root / "data/manifests/hdb_profile")
    return profile(manifest, output, root)


if __name__ == "__main__":
    main()
