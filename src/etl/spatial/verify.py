"""Re-check a spatial stage from its files: hashes, keys, coordinates and the full distance matrix."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from core import EARTH_RADIUS_M, MAX_DISTANCE_M, contract, coordinate, number, read_rows, sha256, write_json
from pipeline import DIAGNOSTIC_COLUMNS, SPATIAL_TABLES


def require(condition, message):
    if not condition:
        raise ValueError(message)


def distance_atan2(lat1, lon1, lat2, lon2):
    """Independent haversine form (atan2), used to cross-check the stored distances."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point(row):
    lat, lon = row["latitude"], row["longitude"]
    require((lat == "") == (lon == ""), f"Half a coordinate pair: {row}")
    if lat == "":
        return None
    parsed = coordinate(lat, lon)
    require(number(parsed[0]) == lat and number(parsed[1]) == lon, f"Non-canonical float text: {lat}, {lon}")
    return parsed


def canonical(value):
    require(value == contract.canonical_text(value), f"Not canonical text: {value!r}")
    return value


def verify(stage_dir, hdb_stage, report=None):
    stage_dir, hdb_stage = Path(stage_dir), Path(hdb_stage)
    manifest = json.loads((stage_dir / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "ready_for_integration", "Stage is not marked ready")
    require(manifest["contract_version"] == contract.VERSION, "Contract version changed since the build")
    for table in SPATIAL_TABLES:
        path = stage_dir / f"{table}.csv"
        expected = manifest["tables"][table]
        require(sha256(path) == expected["sha256"] and path.stat().st_size == expected["bytes"],
                f"{table}.csv differs from the stage manifest")
    require(sha256(stage_dir / "diagnostics.csv") == manifest["diagnostics_sha256"], "diagnostics.csv changed")
    list(read_rows(stage_dir / "diagnostics.csv", DIAGNOSTIC_COLUMNS))
    require(sha256(hdb_stage / "manifest.json") == manifest["hdb_stage"]["manifest_sha256"],
            "The HDB stage is not the one this spatial stage was built from")

    # Buildings: the HDB handoff unchanged except for the coordinate pair.
    source = [r for _, r in read_rows(hdb_stage / "hdb_building.csv", contract.CSV_COLUMNS["hdb_building"])]
    built = [r for _, r in read_rows(stage_dir / "hdb_building.csv", contract.CSV_COLUMNS["hdb_building"])]
    require(len(source) == len(built), "Building count differs from the HDB handoff")
    buildings = {}
    for before, after in zip(source, built):
        require([before[c] for c in contract.CSV_COLUMNS["hdb_building"][:4]] ==
                [after[c] for c in contract.CSV_COLUMNS["hdb_building"][:4]],
                f"Building identity/address changed: {after['building_id']}")
        p = point(after)
        if p:
            buildings[after["building_id"]] = p
    # Two buildings on one point would break (latitude, longitude) as a candidate key (design D2).
    require(len(set(buildings.values())) == len(buildings), "Geocoded buildings share a coordinate pair")

    hawkers, names, fresh = {}, set(), 0
    rows = [r for _, r in read_rows(stage_dir / "hawker_centre.csv", contract.CSV_COLUMNS["hawker_centre"])]
    for r in rows:
        key = (canonical(r["centre_name"]), canonical(r["address"]))
        require(r["hawker_id"] == contract.hawker_id(*key), f"Hawker ID does not follow the contract: {key}")
        require(key not in names, f"Duplicate centre name/address: {key}")
        names.add(key)
        require(r["market_produce_stalls"].isascii() and r["market_produce_stalls"].isdigit(),
                f"Invalid stall count: {r}")
        p = point(r)
        if p:
            hawkers[r["hawker_id"]] = p
            fresh += int(r["market_produce_stalls"]) > 0
    require(len(rows) == manifest["counts"]["hawker_centre"], "Hawker count differs from the manifest")
    require(fresh > 0, "No geocoded fresh-market hawker: Q5 would be empty")

    # Matrix: exactly every geocoded building x geocoded hawker pair, in key order.
    expected = ((b, h) for b in sorted(buildings) for h in sorted(hawkers))
    pairs, worst = 0, 0.0
    for _, r in read_rows(stage_dir / "building_hawker.csv", contract.CSV_COLUMNS["building_hawker"]):
        require((r["building_id"], r["hawker_id"]) == next(expected, None), f"Unexpected or missing pair near {r}")
        stored = float(r["distance_m"])
        require(number(stored) == r["distance_m"] and 0 <= stored <= MAX_DISTANCE_M, f"Bad distance: {r}")
        error = abs(stored - distance_atan2(*buildings[r["building_id"]], *hawkers[r["hawker_id"]]))
        worst = max(worst, error)
        require(error <= 0.001, f"Distance differs by {error} m: {r}")
        pairs += 1
    require(next(expected, None) is None, "Distance matrix is incomplete")

    result = {
        "status": "passed", "stage": manifest["stage"], "contract_version": contract.VERSION,
        "buildings": len(built), "buildings_geocoded": len(buildings), "hawkers": len(rows),
        "hawkers_geocoded": len(hawkers), "fresh_market_hawkers_geocoded": fresh,
        "building_hawker_pairs": pairs, "max_distance_difference_m": worst,
        "checks": ["manifest hashes", "exact headers", "building IDs/towns/addresses unchanged",
                   "coordinate pairs complete, finite, inside Singapore, canonical float text",
                   "no coordinate pair shared by two buildings", "hawker IDs recomputed from contract",
                   "canonical text and unique centre name/address", "complete matrix in key order",
                   "distances within 0.001 m of an independent haversine form"],
    }
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        write_json(report, result)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--hdb-stage", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    verify(args.stage_dir, args.hdb_stage, args.report)
