# HDB frozen data for the group experiments

Download the **2026-10-18 snapshot** from the
[GitHub Release](https://github.com/Junde-W/SD6103_PROJECT/releases/tag/hdb-snapshot-2026-10-18).
It contains the original HDB inputs used for the existing validation results.

| Download | Use |
|---|---|
| `hdb-raw-2026-10-18.zip` | All five CSVs: 989,158 transactions. Use this to set up the full experiment. |
| `hdb-2017-onwards-2026-10-18.zip` | The missing `2017_onwards` CSV: 242,955 transactions. Use this when the other four files are already in place. |
| `hdb_sources.json` | Source URLs, acquisition times, row counts and SHA-256 hashes for all five files. |
| `SHA256SUMS.txt` | SHA-256 checksums of the downloadable assets. |

Open the release while signed into a GitHub account with access to this repository.

## Put the files in the project

From the repository root, extract the full ZIP:

```sh
python -m zipfile -e /path/to/hdb-raw-2026-10-18.zip .
```

For the single-file download, use `hdb-2017-onwards-2026-10-18.zip` in the same command.
Both archives place the CSVs directly under `data/raw/hdb/`.
Then verify the installed files against the repository manifest:

```sh
python -m pip install -r src/etl/hdb/requirements-download.txt
python src/etl/hdb/download.py
```

With all five files installed, the verifier reports `Reused` for each dataset.

## Snapshot contents

| Source | Transactions |
|---|---:|
| `1990_1999` | 287,196 |
| `2000_2012_02` | 369,651 |
| `2012_03_2014` | 52,203 |
| `2015_2016` | 37,153 |
| `2017_onwards` | 242,955 |
| **Total** | **989,158** |

The `2017_onwards` file is `data/raw/hdb/d_8b84c4ee58e3cfc0ece0d773c8ca6abc.csv`.
Its SHA-256 is:

```text
d401fc2e7d2a083576dd388b5ea3d170c2027d2503542de32a84656651ebe947
```

Sources and checksums are recorded in
[`data/manifests/hdb_sources.json`](../manifests/hdb_sources.json).
The publication checks are in [`hdb-2026-10-18.json`](hdb-2026-10-18.json).

## Continue the experiment

Build and check the full HDB stage in a new output directory:

```sh
python src/etl/hdb/pipeline.py --source 2015_2016 --source 2012_03_2014 --source 2017_onwards --source 1990_1999 --source 2000_2012_02 --stage stage5_frozen_20261018 --output data/processed/hdb/stage5_frozen_20261018
python src/etl/hdb/verify.py --stage-dir data/processed/hdb/stage5_frozen_20261018 --report .hdb-qa/stage5_frozen_validation.json
```

Expected output: **27 towns, 10,024 buildings, 147,045 flat profiles and 989,158 transactions**.
Use a new output name for each repeat build.

- **Chen:** run the spatial pipeline against this HDB stage to produce the matching coordinates
  and distance matrix.
- **Sun:** use these same five source files for every cumulative stage and record the selected
  sources, PostgreSQL settings and timing method with the results.
- **LI:** check Q5's selected towns at each cumulative stage and settle one budget threshold
  before the timed runs.
- **Lu:** use the full stage for the index comparison, with the same query files, view definitions
  and `work_mem` as the baseline. The existing 746,203-row experiment provides the initial index
  findings; the full-stage run supplies the final measurements.

The [HDB README](../../src/etl/hdb/README.md) contains the five-stage source order and processing
commands. The [spatial README](../../src/etl/spatial/README.md) describes the spatial inputs and
six-table load order. Data attribution: Housing & Development Board via
[data.gov.sg collection 189](https://data.gov.sg/collections/189/view).
