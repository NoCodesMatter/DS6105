"""Shared helpers for hawker/geolocation processing (standard library only)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("housing_contract", ROOT / "db/schema/contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

HERE = Path(__file__).resolve().parent
SOURCES = ROOT / "data/manifests/spatial_sources.json"
# WU's candidate crosswalk; the spatial owner approves rows in its approved_for_production column.
CROSSWALK = ROOT / "docs/architecture/verification/hawker_geo_validation_results.crosswalk.csv"
COORDINATE_REVIEW = HERE / "coordinate_review.csv"

EARTH_RADIUS_M = 6371008.8  # contract: mean Earth radius, same as housing.haversine_m
MAX_DISTANCE_M = 20015115  # DDL CHECK on building_hawker.distance_m
# Plausibility envelope (design_decisions.md D5 candidate). Every point in both sources lies inside.
SG_LAT, SG_LON = (1.15, 1.50), (103.5, 104.1)

NEA_HEADER = ["name_of_centre", "location_of_centre", "type_of_centre", "owner", "no_of_stalls",
              "no_of_cooked_food_stalls", "no_of_mkt_produce_stalls"]
GEO_HEADER = ["longitude", "latitude", "NAME", "ADDRESS_MYENV"]
HDB_GEO_COLUMNS = ("blk_no", "street", "lat", "lng", "addr")
CROSSWALK_HEADER = ["nea_name", "nea_address", "hawker_id", "status", "geo_source_row", "geo_name",
                    "geo_address", "approved_for_production"]
CROSSWALK_STATUSES = {"exact_name_and_postcode", "postcode_only_review", "unmatched"}
REVIEW_HEADER = ["block", "street_name", "decision", "reason"]
# HDB street abbreviations and the words hdb.csv's geocoded address uses for them.
STREET_WORDS = {"AVE": "AVENUE", "ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "CRES": "CRESCENT",
                "CTRL": "CENTRAL", "NTH": "NORTH", "STH": "SOUTH", "UPP": "UPPER", "LOR": "LORONG",
                "JLN": "JALAN", "BT": "BUKIT", "KG": "KAMPONG", "TG": "TANJONG", "PL": "PLACE", "CL": "CLOSE",
                "TER": "TERRACE", "GDNS": "GARDENS", "HTS": "HEIGHTS", "PK": "PARK", "MKT": "MARKET",
                "CTR": "CENTRE", "C'WEALTH": "COMMONWEALTH", "MT": "MOUNT", "ST.": "SAINT"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_sha256(path):
    """Hash source code as LF-normalised UTF-8 (same convention as the HDB module)."""
    return hashlib.sha256(Path(path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres.

    Same expression and evaluation order as housing.haversine_m in 001_schema.sql, including
    the clamp to [0, 1], so stored values agree with the database check to far below 0.01 m.
    """
    h = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def proximity_class(distance_m):
    """Python mirror of housing.proximity_class, used only for analysis and tests."""
    if distance_m < 0 or distance_m > MAX_DISTANCE_M:
        return None
    if distance_m < 500:
        return "near"
    return "medium" if distance_m < 1000 else "far"


def coordinate(lat_text, lon_text):
    """Parse a source coordinate pair; reject non-finite, (0,0) and points outside Singapore."""
    lat, lon = float(lat_text), float(lon_text)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError(f"Non-finite coordinate: {lat_text}, {lon_text}")
    if lat == 0 and lon == 0:
        raise ValueError("Zero-coordinate sentinel")
    if not (SG_LAT[0] <= lat <= SG_LAT[1] and SG_LON[0] <= lon <= SG_LON[1]):
        raise ValueError(f"Coordinate outside the Singapore envelope: {lat_text}, {lon_text}")
    return lat, lon


def number(value):
    """Round-trip-safe float text for CSV; never rounded."""
    return "" if value is None else repr(float(value))


def geocoded_address_matches(block, street, addr):
    """True when hdb.csv's geocoded address starts with this block and street.

    The addr column records which address the geocoder actually matched (e.g. 2 BEACH RD was
    matched to "2 ANDOVER ROAD CHANGI BEACH CLUB"). If it names another block or road, the
    point belongs to that other address, not to this building.
    """
    expected = block + " " + " ".join(STREET_WORDS.get(word, word) for word in street.split())
    addr = " ".join(addr.upper().split())
    return addr == expected or addr.startswith(expected + " ")


def postcodes(address):
    """All six-digit tokens, so compound NEA postcodes such as S(141001/141002) are kept."""
    return set(re.findall(r"(?<!\d)\d{6}(?!\d)", address.replace("\xa0", " ")))


def read_rows(path, header):
    """Yield (1-based record ordinal, row dict); the header must match exactly."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, strict=True)
        found = next(reader, None)
        if found != list(header):
            raise ValueError(f"Unexpected header in {Path(path).name}: {found}")
        for ordinal, values in enumerate(reader, 1):
            if len(values) != len(found):
                raise ValueError(f"{Path(path).name} record {ordinal} has {len(values)} fields")
            yield ordinal, dict(zip(found, values))


def load_sources(manifest=SOURCES, root=ROOT):
    """Return {label: path} for the frozen spatial inputs after checking every hash."""
    root = Path(root).resolve()
    sources = json.loads(Path(manifest).read_text(encoding="utf-8"))["sources"]
    paths = {}
    for source in sources:
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source path must stay inside the project root")
        if not path.exists():
            raise ValueError(f"Missing input {source['path']}; see src/etl/spatial/README.md")
        if sha256(path) != source["sha256"]:
            raise ValueError(f"Input changed since it was frozen: {source['path']}")
        paths[source["label"]] = path
    missing = {"nea_hawker_centres", "hawker_geo", "hdb_geo"} - paths.keys()
    if missing:
        raise ValueError(f"Source manifest lacks {sorted(missing)}")
    return paths
