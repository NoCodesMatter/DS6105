"""Acquire and freeze the hawker and geolocation inputs (standard library only).

The NEA hawker list and hdb.csv are public and downloaded here. hawker_geo.csv is only
published on NTULearn, so it must be placed by hand; it is hash-checked like the others.
An existing manifest is never rewritten: a changed upstream file is refused, not merged.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

from core import GEO_HEADER, NEA_HEADER, ROOT, SOURCES, read_rows, sha256, write_json

USER_AGENT = "sd6105-spatial-etl/1.0"
NEA_ID = "d_68a42f09f350881996d83f9cd73ab02f"
HDB_GEO_COMMIT = "567427f447e62465ffd248fb70138e7e1f352e1b"  # last commit touching dataset/hdb.csv
API = "https://api-open.data.gov.sg/v1/public/api/datasets/" + NEA_ID
SPECS = {
    "nea_hawker_centres": {
        "path": f"data/raw/spatial/{NEA_ID}.csv",
        "dataset_id": NEA_ID,
        "source_url": f"https://data.gov.sg/datasets/{NEA_ID}/view",
        "acquisition": "data.gov.sg public download API (initiate-download, poll-download)",
    },
    "hdb_geo": {
        "path": "data/raw/spatial/hdb.csv",
        "source_url": f"https://github.com/BlueSkyLT/siteselect_sg/blob/{HDB_GEO_COMMIT}/dataset/hdb.csv",
        "download_url": f"https://raw.githubusercontent.com/BlueSkyLT/siteselect_sg/{HDB_GEO_COMMIT}/dataset/hdb.csv",
        "acquisition": "GitHub raw file pinned to a commit; only hdb.csv is used, as the brief requires",
    },
    "hawker_geo": {
        "path": "data/raw/spatial/hawker_geo.csv",
        "source_url": "NTULearn course page: hawker_geo.csv (extracted from data.gov.sg Hawker Centres GEOJSON)",
        "acquisition": "manual download from NTULearn; not publicly downloadable",
    },
}


def fetch(url, target=None, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if target is None:
                    return json.load(response)
                Path(target).write_bytes(response.read())
                return None
        except OSError as exc:  # resets and timeouts; a 4xx answer will not change on retry
            if attempt == attempts or (isinstance(exc, urllib.error.HTTPError) and exc.code < 500):
                raise
            print(f"Retrying {url.split('?')[0]} after {type(exc).__name__}")  # never print a signed query
            time.sleep(5 * attempt)


def download(label, target):
    if label == "hdb_geo":
        fetch(SPECS[label]["download_url"], target)
        return
    if label != "nea_hawker_centres":
        raise ValueError(f"{SPECS[label]['path']} is missing; download hawker_geo.csv from NTULearn and place it there")
    fetch(f"{API}/initiate-download")
    for _ in range(10):
        url = (fetch(f"{API}/poll-download").get("data") or {}).get("url")
        if url:
            fetch(url, target)  # signed temporary URL: used once, never stored
            return
        time.sleep(5)
    raise ValueError("data.gov.sg did not return a download URL")


def describe(label, path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    known = {"nea_hawker_centres": NEA_HEADER, "hawker_geo": GEO_HEADER}.get(label, header)
    rows = sum(1 for _ in read_rows(path, known))  # also rejects ragged records
    # File time of the original download; moving a file keeps it.
    taken = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {"label": label, **SPECS[label], "sha256": sha256(path), "bytes": path.stat().st_size,
            "rows": rows, "header": header, "snapshot_utc": taken}


def acquire(manifest=SOURCES, root=ROOT):
    root, manifest = Path(root), Path(manifest)
    frozen = {s["label"]: s for s in json.loads(manifest.read_text(encoding="utf-8"))["sources"]} \
        if manifest.exists() else {}
    for label, spec in SPECS.items():
        target = root / spec["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".spatial-download-", dir=target.parent) as temp:
                part = Path(temp) / target.name
                download(label, part)
                if label in frozen and sha256(part) != frozen[label]["sha256"]:
                    raise ValueError(f"Upstream {label} differs from the frozen snapshot; agree a new snapshot first")
                part.replace(target)
            print(f"Downloaded {spec['path']}")
        elif label in frozen and sha256(target) != frozen[label]["sha256"]:
            raise ValueError(f"Local {spec['path']} differs from the frozen snapshot")
        else:  # nothing to compare against before the first freeze
            print(f"{'Verified' if label in frozen else 'Found'} {spec['path']}")
    if not frozen:
        write_json(manifest, {"description": "Frozen inputs of src/etl/spatial; do not edit hashes by hand",
                              "sources": [describe(label, root / SPECS[label]["path"]) for label in SPECS]})
        print(f"Froze {len(SPECS)} inputs in {manifest.relative_to(root)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=SOURCES)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    acquire(args.manifest, args.root)
