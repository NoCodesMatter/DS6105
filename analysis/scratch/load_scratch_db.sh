#!/usr/bin/env bash
# Scratch loader for Lu's index exploration ONLY (not Sun's official loader).
# Usage: load_scratch_db.sh <db_name> <hdb_stage_dir> <spatial_stage_dir>
set -euo pipefail
DB=$1; HDB=$2; SP=$3
PSQL="psql -X -q -v ON_ERROR_STOP=1 -h ${PGHOST:-/tmp} -U ${PGUSER:-postgres}"
$PSQL -d postgres -c "CREATE DATABASE \"$DB\" TEMPLATE template0 ENCODING 'UTF8'"
$PSQL -d "$DB" -f db/schema/001_schema.sql
cols() { head -1 "$1"; }
{
  echo "BEGIN;"
  for t in town:$HDB hdb_building:$SP hdb_flat:$HDB resale_transaction:$HDB hawker_centre:$SP building_hawker:$SP; do
    name=${t%%:*}; dir=${t#*:}; f="$dir/$name.csv"
    echo "\\copy housing.$name ($(cols "$f")) FROM '$f' WITH (FORMAT csv, HEADER true)"
  done
  echo "COMMIT;"
  echo "VACUUM ANALYZE;"
} | $PSQL -d "$DB"
$PSQL -d "$DB" -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname"
