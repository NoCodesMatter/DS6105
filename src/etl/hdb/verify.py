"""Verify saved CSVs, their keys/domains and every original source record."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import uuid

from core import ROOT, HDB_TABLES, FLAT_TYPES, code_sha256, contract, normalize, records, select_sources, sha256, write_json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, lower, upper):
    require(bool(re.fullmatch(r"[0-9]+", value)), f"Non-integer output: {value!r}")
    number = int(value)
    require(lower <= number <= upper, f"Integer out of bounds: {value}")
    return number


def decimal(value, bound):
    require(bool(re.fullmatch(r"[0-9]+\.[0-9]{2}", value)), f"Invalid fixed-point output: {value}")
    require(0 < Decimal(value) < bound, f"Invalid positive numeric: {value}")


def load_table(stage, table, expected):
    path = stage / f"{table}.csv"
    require(sha256(path) == expected["sha256"], f"Output hash mismatch: {table}")
    with path.open("rb") as f:
        require(f.read(3) != b"\xef\xbb\xbf", f"Unexpected UTF-8 BOM: {table}")
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, strict=True)
        header = next(reader)
        require(tuple(header) == contract.CSV_COLUMNS[table], f"Header/order mismatch: {table}")
        rows = []
        for values in reader:
            require(len(values) == len(header), f"Malformed output row: {table}")
            require(all("\x00" not in value for value in values), f"NUL character in output: {table}")
            rows.append(dict(zip(header, values)))
    require(len(rows) == expected["rows"], f"Output count mismatch: {table}")
    pk = contract.CSV_COLUMNS[table][0]
    indexed = {r[pk]: r for r in rows}
    require(len(indexed) == len(rows), f"Duplicate primary key: {table}")
    for row in rows:
        for key, value in row.items():
            if key not in ("latitude", "longitude", "remaining_lease_months"):
                require(value != "", f"Missing required {table}.{key}")
            if key.endswith("_id"):
                require(str(uuid.UUID(value)) == value, f"Noncanonical UUID: {table}.{key}")
    return indexed


def verify(stage, source_manifest=ROOT / "data/manifests/hdb_sources.json", root=ROOT):
    stage = Path(stage)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "ready_for_hdb_handoff", "Stage was not successfully published")
    require(manifest["contract_version"] == contract.VERSION, "Contract version mismatch")
    hash_mode = manifest.get("code_hash_mode", "raw-bytes-v1")
    require(hash_mode in ("utf8-lf-v1", "raw-bytes-v1"), "Unknown source-code hash scheme")
    code_digest = code_sha256 if hash_mode == "utf8-lf-v1" else sha256
    for path, digest in manifest["code_sha256"].items():
        require(code_digest(ROOT / path) == digest, f"Build code changed since this stage was generated: {path}")
    require(sha256(stage / "diagnostics.csv") == manifest["diagnostics_sha256"], "Diagnostics hash mismatch")
    tables = {t: load_table(stage, t, manifest["tables"][t]) for t in HDB_TABLES}
    towns, buildings, flats, transactions = (tables[t] for t in HDB_TABLES)
    for town in towns:
        require(contract.canonical_text(town) == town, "Noncanonical town")
    addresses = set()
    for bid, row in buildings.items():
        require(row["town_name"] in towns, "Building-town foreign key violation")
        for col in ("block", "street_name", "town_name"):
            require(contract.canonical_text(row[col]) == row[col], f"Noncanonical building {col}")
        address = (row["block"], row["street_name"])
        require(address not in addresses, "Duplicate building address")
        addresses.add(address)
        require(contract.building_id(*address) == bid, "Building ID inconsistent with address")
        require(row["latitude"] == row["longitude"] == "", "HDB handoff coordinates must be NULL before Chen enrichment")
    profile_keys = set()
    for fid, row in flats.items():
        require(row["building_id"] in buildings, "Flat-building foreign key violation")
        require(row["flat_type"] in FLAT_TYPES, "Invalid flat type")
        require(contract.canonical_text(row["flat_model"]) == row["flat_model"], "Noncanonical flat model")
        low, high = integer(row["storey_lower"], 1, 32767), integer(row["storey_upper"], 1, 32767)
        require(high >= low, "Inverted storey range")
        year = integer(row["lease_commence_year"], 1, 9999)
        decimal(row["floor_area_sqm"], Decimal("1000000"))
        key = (row["building_id"], row["flat_type"], low, high, row["floor_area_sqm"], row["flat_model"], year)
        require(key not in profile_keys, "Duplicate natural flat profile")
        profile_keys.add(key)
        require(contract.flat_id(*key) == fid, "Flat ID inconsistent with attributes")
    source_keys, source_counts, lease_counts = {}, Counter(), Counter()
    for tid, row in transactions.items():
        require(row["flat_id"] in flats, "Transaction-flat foreign key violation")
        ordinal = integer(row["source_row"], 1, 2147483647)
        require(bool(re.fullmatch(r"d_[0-9a-f]{32}", row["source_dataset"])), "Invalid dataset ID")
        key = (row["source_dataset"], ordinal)
        require(key not in source_keys, "Duplicate source record identity")
        source_keys[key] = row
        require(contract.transaction_id(*key) == tid, "Transaction ID inconsistent with provenance")
        month = date.fromisoformat(row["sale_month"])
        require(month.day == 1 and month.isoformat() == row["sale_month"], "Invalid month marker")
        decimal(row["resale_price"], Decimal("1000000000000"))
        basis, lease = row["lease_basis"], row["remaining_lease_months"]
        require(basis in ("unknown", "reported_years", "reported_months", "estimated_years"), "Invalid lease basis")
        if basis == "unknown":
            require(lease == "", "Unknown lease must be NULL")
        else:
            value = integer(lease, 0, 1188)
            if basis in ("reported_years", "estimated_years"):
                require(value % 12 == 0, "Year-resolution lease has nonzero month remainder")
            if basis == "estimated_years":
                expected = 12 * (99 - (month.year - int(flats[row["flat_id"]]["lease_commence_year"])))
                require(value == expected, "Incorrect estimated lease")
        source_counts[row["source_dataset"]] += 1
        lease_counts[basis] += 1
    require({b["town_name"] for b in buildings.values()} == set(towns), "Unused/missing town dimension")
    require({f["building_id"] for f in flats.values()} == set(buildings), "Unused/missing building dimension")
    require({t["flat_id"] for t in transactions.values()} == set(flats), "Unused/missing flat dimension")
    sources = select_sources(source_manifest, [s["dataset_id"] for s in manifest["sources"]], root)
    frozen = {s["dataset_id"]: s for s in manifest["sources"]}
    checked = 0
    for source in sources:
        sid = source["dataset_id"]
        require(source["sha256"] == frozen[sid]["sha256"], "Stage refers to another input snapshot")
        require(source_counts[sid] == source["rows"], "Source/output count mismatch")
        for ordinal, raw in records(source, root):
            require((sid, ordinal) in source_keys, f"Missing original source record: {sid}/{ordinal}")
            actual = source_keys[(sid, ordinal)]
            normalized, _, _ = normalize(raw)
            building = buildings[flats[actual["flat_id"]]["building_id"]]
            flat = flats[actual["flat_id"]]
            for out_col, source_col in (("town_name", "town"), ("block", "block"), ("street_name", "street_name")):
                require(building[out_col] == normalized[source_col], f"Incorrect source address: {sid}/{ordinal}")
            for col in ("flat_type", "storey_lower", "storey_upper", "floor_area_sqm", "flat_model", "lease_commence_year"):
                require(flat[col] == str(normalized[col]), f"Incorrect source flat field {col}: {sid}/{ordinal}")
            for col in ("sale_month", "resale_price", "remaining_lease_months", "lease_basis"):
                expected = "" if normalized[col] is None else str(normalized[col])
                require(actual[col] == expected, f"Incorrect source transaction field {col}: {sid}/{ordinal}")
            checked += 1
    require(checked == len(transactions) == manifest["input_records"] == manifest["accepted_records"], "Unreconciled transactions")
    require(manifest["fatal_records"] == manifest["dropped_records"] == 0, "Stage contains unresolved fatal errors")
    return {"status": "passed", "stage": manifest["stage"], "contract_version": contract.VERSION,
            "csv_counts": {t: len(rows) for t, rows in tables.items()},
            "source_records_reconciled": checked, "lease_basis_counts": dict(lease_counts),
            "source_dataset_counts": dict(source_counts), "orphan_foreign_keys": 0,
            "duplicate_primary_or_natural_keys": 0, "source_hashes_verified": True,
            "csv_hashes_verified": True, "postgresql_import_executed": False,
            "scope": "Four HDB CSVs before spatial enrichment; not full six-table project acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/hdb_sources.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify(args.stage_dir, args.manifest, args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.report, result)
    print(json.dumps(result, indent=2))
