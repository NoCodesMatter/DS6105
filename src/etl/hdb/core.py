"""Source parsing shared by HDB profiling and CSV generation (standard library only)."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("housing_contract", ROOT / "db/schema/contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
REQUIRED = ("month", "town", "flat_type", "block", "street_name", "storey_range",
            "floor_area_sqm", "flat_model", "lease_commence_date", "resale_price")
FLAT_TYPES = {"1 ROOM", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI GENERATION"}
HDB_TABLES = contract.LOAD_ORDER[:4]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_sha256(path):
    """Hash UTF-8 source with LF line endings; Git may convert LF/CRLF on checkout.

    This normalization applies only to source code, never to data snapshots or CSVs.
    """
    text = Path(path).read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")


def select_sources(manifest_path, selectors=None, root=ROOT):
    manifest_path, root = Path(manifest_path), Path(root).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_sources = manifest["sources"]
    if len({s["dataset_id"] for s in all_sources}) != len(all_sources):
        raise ValueError("Duplicate dataset IDs in source manifest")
    if selectors:
        sources = []
        for key in selectors:
            matches = [s for s in all_sources if key in (s["label"], s["dataset_id"])]
            if len(matches) != 1:
                raise ValueError(f"Source selector is missing or ambiguous: {key}")
            sources.append(matches[0])
        if len({s["dataset_id"] for s in sources}) != len(sources):
            raise ValueError("The same dataset cannot be included twice in one stage")
    else:
        sources = all_sources
    if not sources:
        raise ValueError("No sources selected")
    for source in sources:
        contract.transaction_id(source["dataset_id"], 1)
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source path must stay inside the snapshot root")
        if sha256(path) != source["sha256"]:
            raise ValueError(f"Source snapshot changed: {source['dataset_id']}")
    # Input argument order cannot affect the generated CSV byte order.
    return sorted(sources, key=lambda s: s["dataset_id"])


def records(source, root=ROOT):
    with (Path(root) / source["path"]).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, strict=True)
        header = next(reader)
        if header != source["header"]:
            raise ValueError(f"Header differs from frozen manifest: {source['dataset_id']}")
        if len(set(header)) != len(header) or not set(REQUIRED).issubset(header):
            raise ValueError(f"Missing or duplicated source columns: {header}")
        extra = set(header) - set(REQUIRED) - {"remaining_lease"}
        if extra:
            raise ValueError(f"Unreviewed source columns: {sorted(extra)}")
        count = 0
        # Enumerate CSV records, not lines: quoted newlines remain one record.
        for count, values in enumerate(reader, 1):
            if len(values) != len(header):
                raise ValueError(f"Malformed CSV record {count} in {source['dataset_id']}")
            yield count, dict(zip(header, values))
        if count != source["rows"]:
            raise ValueError(f"Source count differs from manifest: {count} != {source['rows']}")


def remaining_lease(raw, sale_year, lease_year):
    """Only an absent historical column uses the approved year-based estimate."""
    if raw is None:
        value, basis = 12 * (99 - (sale_year - lease_year)), "estimated_years"
        reason = "estimated_lease_out_of_range"
    else:
        text = raw.strip()
        if not text:
            return None, "unknown", "missing_reported_lease"
        if re.fullmatch(r"[0-9]+", text):
            value, basis = 12 * int(text), "reported_years"
        else:
            match = re.fullmatch(r"([0-9]+) years?(?: ([0-9]+) months?)?", text, re.IGNORECASE)
            if not match or (match[2] is not None and int(match[2]) >= 12):
                return None, "unknown", "invalid_reported_lease_syntax"
            value = 12 * int(match[1]) + int(match[2] or 0)
            basis = "reported_months"
        reason = "reported_lease_out_of_range"
    if not 0 <= value <= 1188:
        return None, "unknown", reason
    return value, basis, None


def normalize(raw):
    """Return normalized values, transformation counts and nonfatal issue codes.

    Mandatory invalid fields raise ValueError; no rows are silently discarded.
    """
    out, changes, issues = {}, Counter(), []
    for name in ("town", "block", "street_name", "flat_type", "flat_model"):
        if "\x00" in raw[name]:
            raise ValueError(f"NUL character is not valid PostgreSQL text: {name}")
        out[name] = contract.canonical_text(raw[name])
        if out[name] != raw[name]:
            changes[f"canonicalized_{name}"] += 1
    if out["flat_type"] == "MULTI-GENERATION":
        out["flat_type"] = "MULTI GENERATION"
        changes["mapped_MULTI-GENERATION"] += 1
    if out["flat_type"] not in FLAT_TYPES:
        raise ValueError(f"Unrecognized flat_type: {raw['flat_type']!r}")
    month = raw["month"].strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError(f"Invalid month: {raw['month']!r}")
    sale_date = date.fromisoformat(month + "-01")
    out["sale_month"] = sale_date.isoformat()
    changes["month_to_first_day_marker"] += 1
    storey = re.fullmatch(r"([0-9]+)\s+TO\s+([0-9]+)", raw["storey_range"].strip(), re.IGNORECASE)
    if not storey or not 0 < int(storey[1]) <= int(storey[2]) <= 32767:
        raise ValueError(f"Invalid storey_range: {raw['storey_range']!r}")
    out["storey_lower"], out["storey_upper"] = int(storey[1]), int(storey[2])
    changes["storey_range_split"] += 1
    year = raw["lease_commence_date"].strip()
    if not re.fullmatch(r"[0-9]{1,4}", year) or not 1 <= int(year) <= 9999:
        raise ValueError(f"Invalid lease_commence_date: {year!r}")
    out["lease_commence_year"] = int(year)
    for name, bound in (("floor_area_sqm", Decimal("1000000")), ("resale_price", Decimal("1000000000000"))):
        value = contract.decimal_2(raw[name].strip())
        if not 0 < Decimal(value) < bound:
            raise ValueError(f"{name} outside positive SQL numeric domain: {raw[name]!r}")
        out[name] = value
        if value != raw[name]:
            changes[f"formatted_{name}"] += 1
    value, basis, issue = remaining_lease(raw.get("remaining_lease"), sale_date.year, int(year))
    out["remaining_lease_months"], out["lease_basis"] = value, basis
    changes[f"lease_{basis}"] += 1
    if issue:
        issues.append(issue)
    if sale_date.year < int(year):
        issues.append("transaction_before_lease_commencement_year")
    return out, changes, issues
