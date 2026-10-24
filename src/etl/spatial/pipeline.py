"""Build hawker_centre, geocoded hdb_building and building_hawker CSVs for one HDB stage."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile

from core import (COORDINATE_REVIEW, CROSSWALK, CROSSWALK_HEADER, CROSSWALK_STATUSES, GEO_HEADER, HDB_GEO_COLUMNS,
                  NEA_HEADER, REVIEW_HEADER, ROOT, SOURCES, code_sha256, contract, coordinate,
                  geocoded_address_matches, haversine_m, load_sources, number, postcodes, read_rows, sha256,
                  write_json)

SPATIAL_TABLES = ("hdb_building", "hawker_centre", "building_hawker")
DIAGNOSTIC_COLUMNS = ("entity", "entity_id", "key", "severity", "issue", "detail")
# Nearest same-town building on real data: median 50 m, p99.9 ~200 m. Beyond this, flag for review.
ISOLATION_WARNING_M = 500


def hawker_rows(paths, crosswalk=CROSSWALK):
    """NEA centres (identity and stall counts) with coordinates from the reviewed crosswalk."""
    geo = {}
    for ordinal, row in read_rows(paths["hawker_geo"], GEO_HEADER):
        if row["NAME"] in geo:
            raise ValueError(f"Duplicate hawker_geo NAME: {row['NAME']}")
        geo[row["NAME"]] = (ordinal, row)
    reviewed = {}
    for _, row in read_rows(crosswalk, CROSSWALK_HEADER):
        key = (row["nea_name"], row["nea_address"])
        if key in reviewed or row["status"] not in CROSSWALK_STATUSES:
            raise ValueError(f"Duplicate or invalid crosswalk entry: {key}")
        if (row["status"] == "unmatched") != (row["geo_name"] == ""):
            raise ValueError(f"Crosswalk status and geo_name disagree: {key}")
        if row["geo_name"] and row["approved_for_production"] != "True":
            raise ValueError(f"Crosswalk match is not approved: {key}")
        if row["hawker_id"] != contract.hawker_id(*key):
            raise ValueError(f"Crosswalk hawker_id does not follow the contract: {key}")
        reviewed[key] = row
    rows, issues, claimed = [], [], Counter()
    for _, nea in read_rows(paths["nea_hawker_centres"], NEA_HEADER):
        key = (nea["name_of_centre"], nea["location_of_centre"])
        if key not in reviewed:
            raise ValueError(f"NEA centre without a reviewed crosswalk entry: {key}")
        entry = reviewed.pop(key)
        # Unknown counts must never become 0: that would assert "no fresh market".
        if not re.fullmatch(r"[0-9]+", nea["no_of_mkt_produce_stalls"]):
            raise ValueError(f"Invalid market produce stall count for {key}")
        hid = contract.hawker_id(*key)
        lat = lon = None
        if entry["geo_name"]:
            if entry["geo_name"] not in geo:
                raise ValueError(f"Crosswalk names a missing hawker_geo record: {entry['geo_name']}")
            ordinal, g = geo[entry["geo_name"]]
            if entry["geo_source_row"] != str(ordinal):
                raise ValueError(f"Crosswalk row number does not match hawker_geo.csv for {key}")
            if not postcodes(key[1]) & postcodes(g["ADDRESS_MYENV"]):
                raise ValueError(f"Crosswalk postcodes disagree for {key}")
            claimed[entry["geo_name"]] += 1
            lat, lon = coordinate(g["latitude"], g["longitude"])
        else:
            issues.append(("hawker_centre", hid, contract.canonical_text(key[0]), "warning",
                           "no_hawker_geo_record", "no hawker_geo.csv record in the reviewed crosswalk"))
        rows.append((hid, contract.canonical_text(key[0]), contract.canonical_text(key[1]),
                     int(nea["no_of_mkt_produce_stalls"]), lat, lon))
    if reviewed:
        raise ValueError(f"Crosswalk entries without an NEA centre: {sorted(reviewed)}")
    if any(n > 1 for n in claimed.values()):
        raise ValueError("A hawker_geo record is assigned to more than one NEA centre")
    if len({(r[1], r[2]) for r in rows}) != len(rows):
        raise ValueError("Canonical centre name/address collision")
    for name in sorted(set(geo) - set(claimed)):
        # Not in the prescribed NEA inventory (contract 1.0.0-draft.2); see proposal F-02.
        issues.append(("hawker_geo", "", name, "info", "geo_record_not_in_nea_inventory",
                       geo[name][1]["ADDRESS_MYENV"]))
    return sorted(rows), issues, len(geo)


def building_points(paths, review=COORDINATE_REVIEW):
    """hdb.csv points by canonical address, and the addresses whose point is not used.

    All three rules look at hdb.csv only, so a building gets the same answer in every stage.
    """
    points, rejected = {}, {}
    with Path(paths["hdb_geo"]).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        if not set(HDB_GEO_COLUMNS) <= set(reader.fieldnames or ()):
            raise ValueError(f"hdb.csv lacks {sorted(set(HDB_GEO_COLUMNS) - set(reader.fieldnames or ()))}")
        for row in reader:
            key = (contract.canonical_text(row["blk_no"]), contract.canonical_text(row["street"]))
            if key in points:
                raise ValueError(f"Duplicate hdb.csv address: {key}")
            points[key] = coordinate(row["lat"], row["lng"])
            # 1. The geocoder's own record says the point is another address.
            if not geocoded_address_matches(*key, row["addr"]):
                rejected[key] = ("geocoded_to_other_address", f"hdb.csv addr is {' '.join(row['addr'].split())!r}")
    # 2. A point still given to several addresses does not tell us which building it belongs to.
    owners = defaultdict(list)
    for key, point in points.items():
        if key not in rejected:
            owners[point].append(key)
    for keys in owners.values():
        if len(keys) > 1:
            for key in keys:
                others = ", ".join(" ".join(k) for k in sorted(keys) if k != key)
                rejected[key] = ("ambiguous_source_coordinate", f"same hdb.csv point as {others}")
    # 3. Reviewed cases the two rules cannot see.
    for _, row in read_rows(review, REVIEW_HEADER):
        key = (row["block"], row["street_name"])
        if key not in points or row["decision"] != "reject" or key in rejected:
            raise ValueError(f"Invalid or redundant coordinate review entry: {key}")
        rejected[key] = ("rejected_by_coordinate_review", row["reason"])
    return points, rejected


def isolation_warnings(buildings):
    """Geocoded buildings far from every other geocoded building of the same HDB town."""
    by_town = defaultdict(list)
    for bid, town, block, street, lat, lon in buildings:
        if lat is not None:
            by_town[town].append((bid, f"{block} {street}", lat, lon))
    issues = []
    for town, items in by_town.items():
        for bid, key, lat, lon in items:
            nearest = min((haversine_m(lat, lon, la, lo) for other, _, la, lo in items if other != bid),
                          default=None)
            if nearest is not None and nearest > ISOLATION_WARNING_M:
                issues.append(("hdb_building", bid, key, "warning", "isolated_from_town",
                               f"nearest other {town} building is {nearest:.0f} m away; point kept, review"))
    return issues


def build(hdb_stage, output, stage, manifest=SOURCES, crosswalk=CROSSWALK, review=COORDINATE_REVIEW, root=ROOT):
    output, hdb_stage = Path(output).resolve(), Path(hdb_stage).resolve()
    if output.exists():
        raise ValueError("Choose a new output directory; existing stages are never overwritten")
    hdb_manifest = json.loads((hdb_stage / "manifest.json").read_text(encoding="utf-8"))
    if hdb_manifest.get("status") != "ready_for_hdb_handoff":
        raise ValueError("The HDB stage is not a completed HDB handoff")
    if sha256(hdb_stage / "hdb_building.csv") != hdb_manifest["tables"]["hdb_building"]["sha256"]:
        raise ValueError("hdb_building.csv differs from its HDB stage manifest")
    paths = load_sources(manifest, root)
    hawkers, issues, geo_records = hawker_rows(paths, crosswalk)
    points, rejected = building_points(paths, review)

    buildings, missing = [], Counter()
    for _, row in read_rows(hdb_stage / "hdb_building.csv", contract.CSV_COLUMNS["hdb_building"]):
        key = (row["block"], row["street_name"])
        if row["latitude"] or row["longitude"]:
            raise ValueError("The HDB handoff already contains coordinates")
        if row["building_id"] != contract.building_id(*key):
            raise ValueError(f"Building ID does not follow the contract: {key}")
        if key not in points:
            reason, detail = "no_hdb_geo_record", "no hdb.csv record for this block and street"
        else:
            reason, detail = rejected.get(key, (None, None))
        lat, lon = (None, None) if reason else points[key]
        if reason:
            missing[reason] += 1
            issues.append(("hdb_building", row["building_id"], " ".join(key), "warning", reason, detail))
        buildings.append((row["building_id"], row["town_name"], *key, lat, lon))
    issues += isolation_warnings(buildings)

    geocoded = sorted((b[0], b[4], b[5]) for b in buildings if b[4] is not None)
    centres = [(h[0], h[4], h[5]) for h in hawkers if h[4] is not None]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".spatial-stage-", dir=output.parent) as temp:
        work = Path(temp)

        def write(name, header, rows):
            with (work / name).open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(header)
                writer.writerows(rows)

        # Building order follows the HDB handoff, so a diff against it shows only coordinates.
        write("hdb_building.csv", contract.CSV_COLUMNS["hdb_building"],
              ((*b[:4], number(b[4]), number(b[5])) for b in buildings))
        write("hawker_centre.csv", contract.CSV_COLUMNS["hawker_centre"],
              ((*h[:4], number(h[4]), number(h[5])) for h in hawkers))
        write("building_hawker.csv", contract.CSV_COLUMNS["building_hawker"],
              ((bid, hid, number(haversine_m(blat, blon, hlat, hlon)))
               for bid, blat, blon in geocoded for hid, hlat, hlon in centres))
        write("diagnostics.csv", DIAGNOSTIC_COLUMNS, sorted(issues, key=lambda i: (i[0], i[4], i[2], i[1])))

        counts = {
            "hdb_building": len(buildings), "buildings_geocoded": len(geocoded),
            "buildings_without_coordinates": dict(sorted(missing.items())),
            "buildings_isolated_warning": sum(i[4] == "isolated_from_town" for i in issues),
            "hawker_centre": len(hawkers), "hawkers_geocoded": len(centres),
            "fresh_market_hawkers": sum(h[3] > 0 for h in hawkers),
            "fresh_market_hawkers_geocoded": sum(h[3] > 0 and h[4] is not None for h in hawkers),
            "hawker_geo_records": geo_records,
            "hawker_geo_records_not_in_inventory": sum(i[4] == "geo_record_not_in_nea_inventory" for i in issues),
            "building_hawker": len(geocoded) * len(centres),
        }
        report = {
            "status": "ready_for_integration", "stage": stage, "contract_version": contract.VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "hdb_stage": {"stage": hdb_manifest["stage"], "manifest_sha256": sha256(hdb_stage / "manifest.json"),
                          "hdb_building_sha256": hdb_manifest["tables"]["hdb_building"]["sha256"]},
            "sources": {label: sha256(path) for label, path in sorted(paths.items())},
            "reviews": {Path(crosswalk).name: sha256(crosswalk), Path(review).name: sha256(review)},
            "counts": counts,
            "tables": {t: {"rows": counts[t], "sha256": sha256(work / f"{t}.csv"),
                           "bytes": (work / f"{t}.csv").stat().st_size} for t in SPATIAL_TABLES},
            "diagnostics_sha256": sha256(work / "diagnostics.csv"),
            "load_note": ("Load town, hdb_flat and resale_transaction from the HDB stage; hdb_building, "
                          "hawker_centre and building_hawker from this stage, in contract LOAD_ORDER"),
            "code_hash_mode": "utf8-lf-v1",
            "code_sha256": {p: code_sha256(ROOT / p) for p in (
                "db/schema/contract.py", "src/etl/spatial/core.py", "src/etl/spatial/pipeline.py")},
        }
        write_json(work / "manifest.json", report)
        work.replace(output)
    print(json.dumps({"stage": stage, "counts": counts}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdb-stage", type=Path, required=True, help="Completed HDB stage directory (HE's output)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--manifest", type=Path, default=SOURCES)
    parser.add_argument("--crosswalk", type=Path, default=CROSSWALK)
    parser.add_argument("--review", type=Path, default=COORDINATE_REVIEW)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.hdb_stage, args.output, args.stage, args.manifest, args.crosswalk, args.review, args.root)
