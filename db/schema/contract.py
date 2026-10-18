"""Shared identity/CSV primitives, not an ETL implementation. Python 3.10+."""
from decimal import Decimal, InvalidOperation
import json
import re
import unicodedata
import uuid

VERSION = "1.0.0-draft.2"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:sd6105:housing:schema:1")
CSV_COLUMNS = {
    "town": ("town_name",),
    "hdb_building": ("building_id", "town_name", "block", "street_name", "latitude", "longitude"),
    "hdb_flat": ("flat_id", "building_id", "flat_type", "storey_lower", "storey_upper",
                 "floor_area_sqm", "flat_model", "lease_commence_year"),
    "resale_transaction": ("transaction_id", "flat_id", "sale_month", "resale_price",
                           "remaining_lease_months", "lease_basis", "source_dataset", "source_row"),
    "hawker_centre": ("hawker_id", "centre_name", "address", "market_produce_stalls", "latitude", "longitude"),
    "building_hawker": ("building_id", "hawker_id", "distance_m"),
}
LOAD_ORDER = ("town", "hdb_building", "hdb_flat", "resale_transaction", "hawker_centre", "building_hawker")


def canonical_text(value: str) -> str:
    """NFKC, uppercase and collapse whitespace; no address expansion/fuzzy matching."""
    if not isinstance(value, str):
        raise TypeError("Expected source text")
    result = " ".join(unicodedata.normalize("NFKC", value).upper().split())
    if not result:
        raise ValueError("Empty canonical text")
    return result


def decimal_2(value: str | Decimal) -> str:
    """Serialize exact two-place values. Reject loss of precision, NaN and infinity."""
    try:
        number = Decimal(value)
        rounded = number.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid fixed-point value") from exc
    if not number.is_finite() or rounded != number:
        raise ValueError("Expected a finite value with at most two decimal places")
    return format(rounded, ".2f")


def _key(entity: str, parts: list) -> str:
    payload = json.dumps([entity, *parts], ensure_ascii=False, separators=(",", ":"))
    return str(uuid.uuid5(NAMESPACE, payload))


def building_id(block: str, street_name: str) -> str:
    return _key("building", [canonical_text(block), canonical_text(street_name)])


def flat_id(building: str, flat_type: str, storey_lower: int, storey_upper: int,
            floor_area_sqm: str, flat_model: str, lease_commence_year: int) -> str:
    return _key("flat", [str(uuid.UUID(building)), canonical_text(flat_type),
                        int(storey_lower), int(storey_upper), decimal_2(floor_area_sqm),
                        canonical_text(flat_model), int(lease_commence_year)])


def hawker_id(centre_name: str, address: str) -> str:
    return _key("hawker", [canonical_text(centre_name), canonical_text(address)])


def transaction_id(source_dataset: str, source_row: int) -> str:
    if not re.fullmatch(r"d_[0-9a-f]{32}", source_dataset):
        raise ValueError("Use the data.gov.sg dataset ID")
    if isinstance(source_row, bool) or not isinstance(source_row, int) or source_row < 1:
        raise ValueError("source_row must be a positive 1-based CSV data-record ordinal")
    return _key("transaction", [source_dataset, source_row])
