"""Import an HDB stage into a NEW PostgreSQL database and verify every saved value.

Requires PostgreSQL 15+ and psql. Passwords belong in libpq environment/.pgpass,
never in arguments or evidence. The new database is retained for inspection.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

from core import ROOT, HDB_TABLES, code_sha256, contract, sha256, write_json
from verify import require, verify


def identifier(value):
    require(bool(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value)),
            "Database names must use 1-63 lowercase ASCII letters, digits or underscores")
    return '"' + value + '"'


def literal(value):
    require(not any(c in str(value) for c in ("\n", "\r", "\x00")), "Unsafe SQL path/text")
    return "'" + str(value).replace("'", "''") + "'"


class Psql:
    def __init__(self, executable, host, port, user):
        self.executable = str(executable)
        self.connection = ["--host", host, "--port", str(port), "--username", user]

    def version(self):
        result = subprocess.run([self.executable, "--version"], capture_output=True,
                                encoding="utf-8", errors="replace", check=False)
        require(result.returncode == 0, "Cannot run psql --version")
        return result.stdout.strip()

    def execute(self, database, sql, output=None, expected_failure=None):
        identifier(database)  # A dbname cannot be a libpq connection string.
        env = os.environ.copy()
        env["PGCLIENTENCODING"] = "UTF8"
        with tempfile.TemporaryDirectory(prefix="hdb-psql-") as temporary:
            script = Path(temporary) / "check.sql"
            script.write_text(sql, encoding="utf-8", newline="\n")
            args = [self.executable, "-X", "--no-password", "--quiet", "--no-align",
                    "--tuples-only", "--set", "ON_ERROR_STOP=1", "--set", "VERBOSITY=verbose",
                    *self.connection, "--dbname", database, "--file", str(script)]
            with (Path(output).open("wb") if output else tempfile.TemporaryFile()) as stream:
                result = subprocess.run(args, stdout=stream, stderr=subprocess.PIPE,
                                        env=env, check=False)
                stderr = result.stderr.decode("utf-8", errors="replace")
                states = sorted(set(re.findall(r"(?:ERROR|FATAL):\s+([0-9A-Z]{5}):", stderr)))
                if expected_failure:
                    state, constraint = expected_failure
                    require(result.returncode != 0 and state in states and constraint in stderr,
                            f"Expected rejected COPY ({state}, {constraint}); got exit {result.returncode}, SQLSTATE {states}")
                    return {"sqlstate": state, "constraint": constraint, "psql_exit": result.returncode}
                require(result.returncode == 0,
                        f"psql failed (exit {result.returncode}, SQLSTATE {states}); database retained for inspection")
                if output:
                    return None
                stream.seek(0)
                return stream.read().decode("utf-8").strip()

    def json(self, database, sql):
        return json.loads(self.execute(database, sql))


def import_script(stage, overrides=None):
    overrides = overrides or {}
    lines = ["BEGIN;", "SET LOCAL DateStyle = 'ISO, YMD';", "SET LOCAL standard_conforming_strings = on;"]
    for table in HDB_TABLES:
        path = Path(overrides.get(table, Path(stage) / f"{table}.csv")).resolve().as_posix()
        columns = ", ".join(contract.CSV_COLUMNS[table])
        lines.append(f"\\copy housing.{table} ({columns}) FROM {literal(path)} WITH (FORMAT csv, HEADER true, ENCODING 'UTF8', NULL '')")
    return "\n".join([*lines, "COMMIT;", ""])


def table_counts(psql, database):
    pairs = ", ".join(f"'{table}', (SELECT count(*) FROM housing.{table})" for table in HDB_TABLES)
    return psql.json(database, f"SELECT json_build_object({pairs});")


def rollback_probe(psql, database, stage, work):
    """The same four-COPY transaction must undo earlier tables on final-table failure."""
    bad = work / "rejected_transactions.csv"
    with (stage / "resale_transaction.csv").open(encoding="utf-8", newline="") as source:
        row = next(csv.DictReader(source))
    row["resale_price"] = "0.00"
    with bad.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, contract.CSV_COLUMNS["resale_transaction"], lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    rejection = psql.execute(database, import_script(stage, {"resale_transaction": bad}),
                             expected_failure=("23514", "transaction_positive_price"))
    counts = table_counts(psql, database)
    require(all(value == 0 for value in counts.values()), "Failed COPY left partially imported tables")
    return {"status": "passed", "failed_table": "resale_transaction", "rejection": rejection,
            "counts_after_rollback": counts, "same_import_transaction_builder": True}


def compare_csv(expected, actual, index_path):
    """Compare every parsed value by primary key; disk index avoids million-row RAM use."""
    with closing(sqlite3.connect(index_path)) as index:
        index.execute("CREATE TABLE expected (pk TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        with Path(expected).open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source, strict=True)
            header = next(reader)
            count = 0
            for row in reader:
                require(len(row) == len(header), "Malformed expected CSV row")
                index.execute("INSERT INTO expected VALUES (?, ?)",
                              (row[0], json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
                count += 1
        checked = 0
        with Path(actual).open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source, strict=True)
            require(next(reader) == header, "Database export header differs from contract")
            for row in reader:
                require(len(row) == len(header), "Malformed PostgreSQL export row")
                result = index.execute("SELECT payload FROM expected WHERE pk = ?", (row[0],)).fetchone()
                require(result is not None, "Database export has an unexpected or duplicate primary key")
                require(json.loads(result[0]) == row, f"Database roundtrip changed values for key {row[0]}")
                index.execute("DELETE FROM expected WHERE pk = ?", (row[0],))
                checked += 1
        missing = index.execute("SELECT count(*) FROM expected").fetchone()[0]
        require(missing == 0 and checked == count, "Database export is missing source CSV records")
    return {"status": "passed", "rows_compared": checked, "columns_compared": len(header),
            "comparison": "all parsed strings, matched by primary key; order and CSV line endings ignored"}


def roundtrip(psql, database, stage, work):
    results = {}
    for table in HDB_TABLES:
        path = work / f"{table}.csv"
        columns = ", ".join(contract.CSV_COLUMNS[table])
        psql.execute(database, "SET DateStyle = 'ISO, YMD';\n"
                     f"COPY (SELECT {columns} FROM housing.{table}) TO STDOUT WITH (FORMAT csv, HEADER true, ENCODING 'UTF8', NULL '');",
                     output=path)
        results[table] = compare_csv(stage / path.name, path, work / f"{table}.sqlite")
    return results


def sql_checks(psql, database, preflight):
    checks = {
        "orphan_buildings": "SELECT count(*) FROM housing.hdb_building b LEFT JOIN housing.town t USING (town_name) WHERE t.town_name IS NULL",
        "orphan_flats": "SELECT count(*) FROM housing.hdb_flat f LEFT JOIN housing.hdb_building b USING (building_id) WHERE b.building_id IS NULL",
        "orphan_transactions": "SELECT count(*) FROM housing.resale_transaction t LEFT JOIN housing.hdb_flat f USING (flat_id) WHERE f.flat_id IS NULL",
        "unexpected_coordinates": "SELECT count(*) FROM housing.hdb_building WHERE latitude IS NOT NULL OR longitude IS NOT NULL",
        "invalid_months": "SELECT count(*) FROM housing.resale_transaction WHERE extract(day FROM sale_month) <> 1 OR sale_month NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-01'",
        "invalid_prices": "SELECT count(*) FROM housing.resale_transaction WHERE NOT (resale_price > 0 AND resale_price < 'Infinity'::numeric)",
        "invalid_lease_nulls": "SELECT count(*) FROM housing.resale_transaction WHERE (lease_basis = 'unknown') <> (remaining_lease_months IS NULL)",
        "invalid_lease_ranges": "SELECT count(*) FROM housing.resale_transaction WHERE remaining_lease_months NOT BETWEEN 0 AND 1188",
        "invalid_lease_year_precision": "SELECT count(*) FROM housing.resale_transaction WHERE lease_basis IN ('reported_years','estimated_years') AND remaining_lease_months % 12 <> 0",
        "invalid_estimated_lease_formula": "SELECT count(*) FROM housing.resale_transaction t JOIN housing.hdb_flat f USING (flat_id) WHERE lease_basis = 'estimated_years' AND remaining_lease_months <> 12 * (99 - (extract(year FROM sale_month)::int - lease_commence_year))",
        "invalid_source_ordinals": "SELECT count(*) FROM (SELECT source_dataset FROM housing.resale_transaction GROUP BY source_dataset HAVING min(source_row) <> 1 OR max(source_row) <> count(*) OR count(DISTINCT source_row) <> count(*)) s",
        "duplicate_building_addresses": "SELECT count(*) FROM (SELECT block, street_name FROM housing.hdb_building GROUP BY block, street_name HAVING count(*) > 1) s",
        "duplicate_flat_profiles": "SELECT count(*) FROM (SELECT building_id, flat_type, storey_lower, storey_upper, floor_area_sqm, flat_model, lease_commence_year FROM housing.hdb_flat GROUP BY building_id, flat_type, storey_lower, storey_upper, floor_area_sqm, flat_model, lease_commence_year HAVING count(*) > 1) s",
        "duplicate_source_keys": "SELECT count(*) FROM (SELECT source_dataset, source_row FROM housing.resale_transaction GROUP BY source_dataset, source_row HAVING count(*) > 1) s",
        "unvalidated_constraints": "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = 'housing' AND NOT c.convalidated",
    }
    optional = {"latitude", "longitude", "remaining_lease_months"}
    for table in HDB_TABLES:
        pk = contract.CSV_COLUMNS[table][0]
        checks[f"{table}_duplicate_primary_keys"] = f"SELECT count(*) FROM (SELECT {pk} FROM housing.{table} GROUP BY {pk} HAVING count(*) > 1) s"
        nulls = " OR ".join(f"{col} IS NULL" for col in contract.CSV_COLUMNS[table] if col not in optional)
        checks[f"{table}_unexpected_nulls"] = f"SELECT count(*) FROM housing.{table} WHERE {nulls}"
    pairs = ", ".join(f"'{name}', ({sql})" for name, sql in checks.items())
    diagnostics = psql.json(database, f"SELECT json_build_object({pairs});")
    require(all(value == 0 for value in diagnostics.values()), f"SQL diagnostics failed: {diagnostics}")
    counts = table_counts(psql, database)
    require(counts == preflight["csv_counts"], "Database table counts differ from preflight")
    grouped = {}
    for column, expected in (("source_dataset", "source_dataset_counts"), ("lease_basis", "lease_basis_counts")):
        grouped[column] = psql.json(database,
            f"SELECT json_object_agg({column}, n) FROM (SELECT {column}, count(*) n FROM housing.resale_transaction GROUP BY {column}) s;")
        require(grouped[column] == preflight[expected], f"Database {column} counts differ from preflight")
    nulls = psql.json(database, "SELECT json_build_object('unknown_lease_rows', (SELECT count(*) FROM housing.resale_transaction WHERE remaining_lease_months IS NULL), 'buildings_with_null_coordinates', (SELECT count(*) FROM housing.hdb_building WHERE latitude IS NULL AND longitude IS NULL));")
    return {"status": "passed", "table_counts": counts, "violations": diagnostics,
            "source_dataset_counts": grouped["source_dataset"], "lease_basis_counts": grouped["lease_basis"],
            "expected_null_counts": nulls}


def constraint_probes(psql, database):
    target = "WHERE transaction_id = (SELECT transaction_id FROM housing.resale_transaction LIMIT 1)"
    transaction = lambda values: f"UPDATE housing.resale_transaction SET {values} {target}"
    probes = {
        "duplicate_primary_key": ("INSERT INTO housing.town SELECT * FROM housing.town LIMIT 1", "23505"),
        "foreign_key": (transaction("flat_id = '00000000-0000-0000-0000-000000000000'"), "23503"),
        "month_day": (transaction("sale_month = DATE '2015-01-02'"), "23514"),
        "invalid_calendar_date": (transaction("sale_month = '2015-02-30'::date"), "22008"),
        "zero_price": (transaction("resale_price = 0"), "23514"),
        "numeric_overflow": (transaction("resale_price = 1000000000000"), "22003"),
        "price_null": (transaction("resale_price = NULL"), "23502"),
        "lease_range": (transaction("lease_basis = 'reported_months', remaining_lease_months = 1189"), "23514"),
        "unknown_lease_nonnull": (transaction("lease_basis = 'unknown', remaining_lease_months = 12"), "23514"),
        "year_lease_precision": (transaction("lease_basis = 'reported_years', remaining_lease_months = 13"), "23514"),
        "source_ordinal": (transaction("source_row = 0"), "23514"),
        "coordinate_pair": ("UPDATE housing.hdb_building SET latitude = 1 WHERE building_id = (SELECT building_id FROM housing.hdb_building LIMIT 1)", "23514"),
        "canonical_text": ("INSERT INTO housing.town VALUES ('lowercase')", "23514"),
    }
    results = {}
    for name, (statement, state) in probes.items():
        sql = f"""BEGIN;
DO $probe$
DECLARE actual_state text;
BEGIN
  BEGIN
    {statement};
    RAISE EXCEPTION 'Expected rejection did not occur';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE;
    IF actual_state <> '{state}' THEN
      RAISE EXCEPTION 'Wrong SQLSTATE: %, expected {state}', actual_state;
    END IF;
  END;
END $probe$;
ROLLBACK;
SELECT 'passed';
"""
        require(psql.execute(database, sql) == "passed", f"Constraint probe did not pass: {name}")
        results[name] = {"status": "passed", "expected_sqlstate": state, "observed_sqlstate": state}
    return results


def run(args):
    identifier(args.database)
    identifier(args.maintenance_db)
    require(args.database != args.maintenance_db, "Verification requires a separate NEW database")
    stage = args.stage_dir.resolve()
    manifest_path = args.manifest or args.root / "data/manifests/hdb_sources.json"
    preflight = verify(stage, manifest_path, args.root)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    psql = Psql(args.psql, args.host, args.port, args.user)
    client = psql.version()
    server = psql.json(args.maintenance_db,
        "SELECT json_build_object('version', version(), 'version_num', current_setting('server_version_num')::int);")
    require(server["version_num"] >= 150000, "Schema contract requires PostgreSQL 15+")
    # CREATE DATABASE must fail if the name exists. Never reset/drop an existing database.
    psql.execute(args.maintenance_db,
                 f"CREATE DATABASE {identifier(args.database)} WITH TEMPLATE template0 ENCODING 'UTF8';")
    schema = ROOT / "db/schema/001_schema.sql"
    psql.execute(args.database, schema.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="hdb-postgres-verify-") as temporary:
        work = Path(temporary)
        rollback = rollback_probe(psql, args.database, stage, work)
        psql.execute(args.database, import_script(stage))
        diagnostics = sql_checks(psql, args.database, preflight)
        probes = constraint_probes(psql, args.database)
        fidelity = roundtrip(psql, args.database, stage, work)
    return {"status": "passed", "checked_utc": datetime.now(timezone.utc).isoformat(),
            "postgresql_import_executed": True, "database": args.database, "database_retained": True,
            "server": server, "client_version": client, "contract_version": contract.VERSION,
            "schema_sha256": sha256(schema), "schema_utf8_lf_sha256": code_sha256(schema),
            "verification_code_sha256": code_sha256(Path(__file__)),
            "verification_code_hash_mode": "utf8-lf-v1",
            "stage": manifest["stage"], "stage_manifest_sha256": sha256(stage / "manifest.json"),
            "source_snapshots": manifest["sources"], "csv_tables": manifest["tables"],
            "preflight": preflight, "transaction_rollback_probe": rollback,
            "sql_checks": diagnostics, "constraint_probes": probes, "full_value_roundtrip": fidelity,
            "full_project_acceptance_executed": False,
            "scope": "Four HDB tables before geocoding; no hawker/spatial completeness claim"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--psql", default="psql")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", required=True)
    parser.add_argument("--maintenance-db", default="postgres")
    parser.add_argument("--database", required=True, help="NEW database name; an existing name fails")
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    # Replace stale successful evidence before any attempt, including failed preflight.
    write_json(args.report, {"status": "running", "database": args.database,
                            "started_utc": datetime.now(timezone.utc).isoformat()})
    try:
        result = run(args)
    except Exception as exc:
        # Do not persist subprocess diagnostics, connection details, or exception data.
        result = {"status": "failed", "database": args.database, "error_type": type(exc).__name__,
                  "checked_utc": datetime.now(timezone.utc).isoformat(),
                  "message": "Import verification did not complete; any created database is retained for inspection."}
        write_json(args.report, result)
        print(json.dumps(result, indent=2))
        raise
    write_json(args.report, result)
    print(json.dumps({"status": result["status"], "database": args.database,
                      "table_counts": result["sql_checks"]["table_counts"], "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
