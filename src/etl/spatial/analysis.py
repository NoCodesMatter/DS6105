"""Distance and coverage figures behind the proximity thresholds and proposals F-02 / F-03.

Reads a built spatial stage plus the HDB stage it came from (for transaction weights).
Nearest centres follow the database views: minimum distance, ties to the smaller hawker_id.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from core import (CROSSWALK, CROSSWALK_HEADER, GEO_HEADER, ROOT, SOURCES, contract, coordinate, haversine_m,
                  load_sources, read_rows)

PERCENTILES = (0, 10, 25, 50, 75, 90, 95, 99, 100)
THRESHOLDS = ((300, 800), (400, 800), (500, 1000), (500, 1500), (750, 1500))
CAPS = (1000, 1500, 2000, 2500, 3000)
CLASSES = ("near", "medium", "far")


def classify(distance, near=500, far=1000):
    return "near" if distance < near else "medium" if distance < far else "far"


def quantiles(pairs):
    """Weighted nearest-rank percentiles of (value, weight) pairs."""
    pairs = sorted(pairs)
    total, out = sum(w for _, w in pairs), {}
    for p in PERCENTILES:
        target, running = max(p / 100 * total, 1e-9), 0
        for value, weight in pairs:
            running += weight
            if running >= target:
                out[f"p{p}"] = round(value, 1)
                break
    return out


def analyse(spatial_stage, hdb_stage, manifest=SOURCES, root=ROOT):
    spatial_stage, hdb_stage = Path(spatial_stage), Path(hdb_stage)
    buildings, hawkers = {}, {}
    for _, r in read_rows(spatial_stage / "hdb_building.csv", contract.CSV_COLUMNS["hdb_building"]):
        buildings[r["building_id"]] = (r["town_name"], *(coordinate(r["latitude"], r["longitude"])
                                                         if r["latitude"] else (None, None)))
    for _, r in read_rows(spatial_stage / "hawker_centre.csv", contract.CSV_COLUMNS["hawker_centre"]):
        if r["latitude"]:
            hawkers[r["hawker_id"]] = int(r["market_produce_stalls"])
    nearest, fresh = {}, {}
    for _, r in read_rows(spatial_stage / "building_hawker.csv", contract.CSV_COLUMNS["building_hawker"]):
        d, bid = float(r["distance_m"]), r["building_id"]
        # Rows are sorted by hawker_id inside a building, so a strict < keeps the smaller ID on ties.
        if bid not in nearest or d < nearest[bid]:
            nearest[bid] = d
        if hawkers[r["hawker_id"]] > 0 and (bid not in fresh or d < fresh[bid]):
            fresh[bid] = d

    flat = {r["flat_id"]: (r["building_id"], r["flat_type"])
            for _, r in read_rows(hdb_stage / "hdb_flat.csv", contract.CSV_COLUMNS["hdb_flat"])}
    sales, cells = Counter(), Counter()  # sales per building; per (building, flat_type)
    periods = defaultdict(Counter)  # most geo-only centres opened after 2016
    for _, r in read_rows(hdb_stage / "resale_transaction.csv", contract.CSV_COLUMNS["resale_transaction"]):
        bid, flat_type = flat[r["flat_id"]]
        sales[bid] += 1
        cells[bid, flat_type] += 1
        periods[bid]["2017+" if r["sale_month"] >= "2017-01-01" else "before 2017"] += 1
    covered = [b for b in buildings if b in nearest]

    def occupancy(distances, near=500, far=1000):
        out = {c: {"buildings": 0, "transactions": 0} for c in CLASSES}
        for b in covered:
            if b in distances:
                c = classify(distances[b], near, far)
                out[c]["buildings"] += 1
                out[c]["transactions"] += sales[b]
        return out

    def q4_cells(near=500, far=1000):
        seen = defaultdict(set)
        for b, flat_type in cells:
            if b in nearest:
                seen[buildings[b][0], flat_type].add(classify(nearest[b], near, far))
        return {"cells_with_spatial_sales": len(seen),
                "cells_with_near_and_far": sum({"near", "far"} <= s for s in seen.values())}

    # F-02: hawker_geo records outside the NEA inventory (geo-only centres).
    paths = load_sources(manifest, root)
    matched = {r["geo_name"] for _, r in read_rows(CROSSWALK, CROSSWALK_HEADER) if r["geo_name"]}
    geo_only = [coordinate(r["latitude"], r["longitude"]) for _, r in read_rows(paths["hawker_geo"], GEO_HEADER)
                if r["NAME"] not in matched]
    moved, change = Counter(), Counter()
    for b in covered:
        _, lat, lon = buildings[b]
        closest = min(haversine_m(lat, lon, la, lo) for la, lo in geo_only)
        if closest < nearest[b]:
            moved["buildings"] += 1
            moved["transactions"] += sales[b]
            before, after = classify(nearest[b]), classify(closest)
            if before != after:
                for period, n in periods[b].items():
                    change[f"{before}->{after}", period] += n

    caps = {}
    for cap in CAPS:
        caps[cap] = {"q5_buildings_beyond": sum(fresh[b] > cap for b in covered if b in fresh),
                     "q5_transactions_beyond": sum(sales[b] for b in covered if b in fresh and fresh[b] > cap),
                     "q4_buildings_beyond": sum(nearest[b] > cap for b in covered),
                     "q4_transactions_beyond": sum(sales[b] for b in covered if nearest[b] > cap)}
    p95 = quantiles([(fresh[b], 1) for b in covered if b in fresh])["p95"]
    suggested = min(2000, next(c for c in range(250, 100000, 250) if c >= p95))
    return {
        "spatial_stage": json.loads((spatial_stage / "manifest.json").read_text(encoding="utf-8"))["stage"],
        "coverage": {"buildings": len(buildings), "buildings_geocoded": len(covered),
                     "transactions": sum(sales.values()),
                     "transactions_with_spatial_coverage": sum(sales[b] for b in covered)},
        "nearest_hawker_m": {"buildings": quantiles([(nearest[b], 1) for b in covered]),
                             "transactions": quantiles([(nearest[b], sales[b]) for b in covered if sales[b]])},
        "nearest_fresh_market_hawker_m": {
            "buildings": quantiles([(fresh[b], 1) for b in covered if b in fresh]),
            "transactions": quantiles([(fresh[b], sales[b]) for b in covered if b in fresh and sales[b]])},
        "current_classes": {"q4_nearest_hawker": occupancy(nearest), "q5_nearest_fresh_market": occupancy(fresh),
                            "q4_town_flat_type_cells": q4_cells()},
        "threshold_sensitivity": [{"near_below_m": n, "far_from_m": f,
                                   "q4": {c: v["transactions"] for c, v in occupancy(nearest, n, f).items()},
                                   "q5": {c: v["transactions"] for c, v in occupancy(fresh, n, f).items()},
                                   **q4_cells(n, f)} for n, f in THRESHOLDS],
        "f03_caps": caps,
        "f03_suggested_cap_m": {"p95_building_nearest_fresh_m": p95, "rule": "smallest 250 m step >= p95, max 2000",
                                "value": suggested},
        "f02_geo_only_centres": {"centres": len(geo_only), "closer_than_nearest_nea": dict(moved),
                                 "q4_class_changes_transactions": {f"{k[0]} ({k[1]})": v
                                                                   for k, v in sorted(change.items())}},
    }


def markdown(result):
    cov, lines = result["coverage"], []
    lines += [f"# Distance analysis: {result['spatial_stage']}", "",
              (f"Geocoded buildings {cov['buildings_geocoded']:,} / {cov['buildings']:,}; transactions with spatial "
               f"coverage {cov['transactions_with_spatial_coverage']:,} / {cov['transactions']:,}."), "",
              "## Nearest-centre distance (m)", "", "| Distribution | " + " | ".join(f"p{p}" for p in PERCENTILES) + " |",
              "|---|" + "---:|" * len(PERCENTILES)]
    for name, key in (("nearest hawker", "nearest_hawker_m"), ("nearest fresh-market", "nearest_fresh_market_hawker_m")):
        for weight in ("buildings", "transactions"):
            q = result[key][weight]
            lines.append(f"| {name}, by {weight} | " + " | ".join(f"{q[f'p{p}']:,.0f}" for p in PERCENTILES) + " |")
    lines += ["", "## Classes under the contract (near < 500 m, medium < 1000 m, far >= 1000 m)", "",
              "| Query basis | " + " | ".join(f"{c} (buildings / transactions)" for c in CLASSES) + " |", "|---|---|---|---|"]
    for name, key in (("Q4 nearest hawker", "q4_nearest_hawker"), ("Q5 nearest fresh-market", "q5_nearest_fresh_market")):
        occ = result["current_classes"][key]
        lines.append(f"| {name} | " + " | ".join(f"{occ[c]['buildings']:,} / {occ[c]['transactions']:,}" for c in CLASSES) + " |")
    cells = result["current_classes"]["q4_town_flat_type_cells"]
    lines += ["", (f"Q4 town x flat_type cells with both near and far sales: {cells['cells_with_near_and_far']} of "
                   f"{cells['cells_with_spatial_sales']}."), "", "## Threshold sensitivity (transactions)", "",
              "| near < | far >= | Q4 near / medium / far | Q5 near / medium / far | Q4 cells with near and far |",
              "|---:|---:|---|---|---:|"]
    for s in result["threshold_sensitivity"]:
        lines.append(f"| {s['near_below_m']} | {s['far_from_m']} | " + " / ".join(f"{s['q4'][c]:,}" for c in CLASSES)
                     + " | " + " / ".join(f"{s['q5'][c]:,}" for c in CLASSES)
                     + f" | {s['cells_with_near_and_far']} of {s['cells_with_spatial_sales']} |")
    lines += ["", "## F-03: sales beyond a maximum effective distance", "",
              "| Cap (m) | Q5 buildings / transactions beyond | Q4 buildings / transactions beyond |", "|---:|---|---|"]
    for cap, v in result["f03_caps"].items():
        lines.append(f"| {cap} | {v['q5_buildings_beyond']:,} / {v['q5_transactions_beyond']:,} | "
                     f"{v['q4_buildings_beyond']:,} / {v['q4_transactions_beyond']:,} |")
    s, f = result["f03_suggested_cap_m"], result["f02_geo_only_centres"]
    lines += ["", f"Rule from F-03 ({s['rule']}): p95 = {s['p95_building_nearest_fresh_m']:,.0f} m -> {s['value']} m.", "",
              "## F-02: geo-only centres (not in the NEA inventory)", "",
              (f"{f['centres']} geo-only centres are closer than the nearest NEA centre for "
               f"{f['closer_than_nearest_nea'].get('buildings', 0):,} buildings "
               f"({f['closer_than_nearest_nea'].get('transactions', 0):,} transactions)."), "",
              "| Q4 class change if they were included | Transactions |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k, v in f["q4_class_changes_transactions"].items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spatial-stage", type=Path, required=True)
    parser.add_argument("--hdb-stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Directory for distance_analysis.md")
    parser.add_argument("--manifest", type=Path, default=SOURCES)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report = markdown(analyse(args.spatial_stage, args.hdb_stage, args.manifest, args.root))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "distance_analysis.md").write_text(report, encoding="utf-8")
    print(report)
