"""Download and freeze the five prescribed public HDB CSVs. Requires requests."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[3]
DATASETS = (
    ("d_ebc5ab87086db484f88045b47411ebc5", "1990_1999"),
    ("d_43f493c6c50d54243cc1eab0df142d6a", "2000_2012_02"),
    ("d_2d5ff9ea31397b66239f245f57751537", "2012_03_2014"),
    ("d_ea9ed51da2787afaf8e51f827c304208", "2015_2016"),
    ("d_8b84c4ee58e3cfc0ece0d773c8ca6abc", "2017_onwards"),
)
ATTEMPTS = 6


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def object_url(url):
    """Accept only this collection's official HTTPS object storage URLs."""
    if not isinstance(url, str):
        raise ValueError("Invalid source object URL")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "s3.ap-southeast-1.amazonaws.com"
            or not parts.path.startswith("/table-downloads-ingest.data.gov.sg/")
            or parts.fragment):
        raise ValueError("Unexpected source object URL; expected official HTTPS storage")
    return url


def load_manifest(path):
    if not path.exists():
        return {"collection_url": "https://data.gov.sg/collections/189/view", "sources": []}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise ValueError("Invalid source manifest: expected a sources list")
    labels = dict(DATASETS)
    seen = set()
    for entry in manifest["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid source manifest entry")
        dataset_id = entry.get("dataset_id")
        if not isinstance(dataset_id, str) or dataset_id not in labels or dataset_id in seen:
            raise ValueError("Invalid source manifest: unknown or duplicate dataset_id")
        seen.add(dataset_id)
        if (entry.get("label") != labels[dataset_id]
                or entry.get("path") != f"data/raw/hdb/{dataset_id}.csv"
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError(f"Invalid source manifest identity: {dataset_id}")
        if any(type(entry.get(key)) is not int or entry[key] <= 0 for key in ("rows", "bytes")):
            raise ValueError(f"Invalid source manifest counts: {dataset_id}")
        header = entry.get("header")
        if (not isinstance(header, list) or not all(isinstance(v, str) and v for v in header)
                or len(header) != len(set(header)) or not {"month", "resale_price"} <= set(header)):
            raise ValueError(f"Invalid source manifest header: {dataset_id}")
        object_url(entry.get("download_object_url"))
        if urlsplit(entry["download_object_url"]).query:
            raise ValueError("Source manifest must not retain signed URL credentials")
    return manifest


def fetch_csv(session, url, part):
    object_url(url)
    for attempt in range(ATTEMPTS):
        try:
            # Do not follow a storage redirect to an unvalidated host.
            with session.get(url, stream=True, timeout=(15, 120), allow_redirects=False) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    pass
                elif response.status_code != 200:
                    raise RuntimeError(f"CSV download returned HTTP {response.status_code}")
                else:
                    with part.open("wb") as f:
                        for chunk in response.iter_content(1024 * 1024):
                            f.write(chunk)
                    return
        except requests.RequestException:
            # Request exceptions can contain temporary signed URLs; do not expose them.
            pass
        part.unlink(missing_ok=True)
        if attempt + 1 < ATTEMPTS:
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError("CSV download unavailable after bounded retries") from None


def download(root=ROOT):
    root = Path(root).resolve()
    target = root / "data/raw/hdb"
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "data/manifests/hdb_sources.json"
    manifest = load_manifest(manifest_path)
    saved = {s["dataset_id"]: s for s in manifest["sources"]}
    session = requests.Session()
    last_api_call = 0.0

    def api(url):
        nonlocal last_api_call
        # Public API quota: at most 5 requests/minute. Never log signed URLs.
        for attempt in range(ATTEMPTS):
            time.sleep(max(0, 13 - (time.monotonic() - last_api_call)))
            last_api_call = time.monotonic()
            try:
                with session.get(url, timeout=(15, 60), allow_redirects=False) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        continue
                    if not 200 <= response.status_code < 300:
                        raise RuntimeError(f"Public data API returned HTTP {response.status_code}")
                    payload = response.json()
            except requests.RequestException:
                continue
            if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
                raise RuntimeError("Public data API reported an unsuccessful response")
            return payload["data"]
        raise RuntimeError("Public data API unavailable after bounded retries")

    def acquire(dataset_id, label):
        path = target / f"{dataset_id}.csv"
        if path.exists() and dataset_id in saved:
            if sha256(path) != saved[dataset_id]["sha256"]:
                raise ValueError(f"Snapshot hash mismatch: {path.name}; refusing to overwrite")
            print(f"Reused frozen snapshot: {label}", flush=True)
            return
        with tempfile.NamedTemporaryFile(prefix=f"{dataset_id}.", suffix=".part", dir=target, delete=False) as f:
            part = Path(f.name)
        try:
            restored = False
            if dataset_id in saved:
                # A stripped object URL may be public, but may also need a fresh signature.
                try:
                    fetch_csv(session, saved[dataset_id]["download_object_url"], part)
                    restored = True
                except RuntimeError:
                    pass
            if not restored:
                metadata = api(f"https://api-production.data.gov.sg/v2/public/api/datasets/{dataset_id}/metadata")
                api(f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/initiate-download")
                for attempt in range(ATTEMPTS):
                    data = api(f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download")
                    if data.get("url"):
                        break
                if not data.get("url"):
                    raise RuntimeError(f"Download not ready: {dataset_id}")
                url = data["url"]
                fetch_csv(session, url, part)
            with part.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, strict=True)
                header = next(reader, [])
                count = sum(1 for _ in reader)
            if "month" not in header or "resale_price" not in header or not count:
                raise ValueError(f"Unexpected or empty source CSV: {dataset_id}")
            digest = sha256(part)
            if dataset_id in saved:
                entry = saved[dataset_id]
                if entry["sha256"] != digest:
                    raise ValueError(f"Live {dataset_id} changed from the frozen manifest; use a NEW snapshot root")
                if (entry["header"], entry["rows"], entry["bytes"]) != (header, count, part.stat().st_size):
                    raise ValueError(f"Source manifest statistics disagree with frozen bytes: {dataset_id}")
            if path.exists():
                if sha256(path) != digest:
                    raise ValueError(f"Existing untracked snapshot differs: {path}; refusing to overwrite")
            else:
                part.replace(path)
            if dataset_id not in saved:
                saved[dataset_id] = {
                    "dataset_id": dataset_id, "label": label,
                    "source_url": f"https://data.gov.sg/datasets/{dataset_id}/view",
                    "download_object_url": urlunsplit((*urlsplit(url)[:3], "", "")),
                    "snapshot_utc": datetime.now(timezone.utc).isoformat(),
                    "path": path.relative_to(root).as_posix(), "sha256": digest,
                    "bytes": path.stat().st_size, "rows": count, "header": header,
                    "metadata": metadata,
                }
                manifest["sources"] = [saved[d] for d, _ in DATASETS if d in saved]
                save_json(manifest_path, manifest)
            print(f"Downloaded {label}: {count:,} records, {path.stat().st_size:,} bytes", flush=True)
        finally:
            part.unlink(missing_ok=True)

    try:
        for dataset_id, label in DATASETS:
            acquire(dataset_id, label)
    finally:
        session.close()
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    download(parser.parse_args().root)
