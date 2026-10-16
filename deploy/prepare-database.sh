#!/usr/bin/env bash
# Run as root by systemd only while the app is stopped.
set -euo pipefail
APP_DIR=/opt/parenting-together
ENV_FILE=/etc/parenting-together.env
BACKUPS=/var/backups/parenting-together
set -a
. "$ENV_FILE"
set +a
install -d -m 700 "$BACKUPS"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "Preparing local PostgreSQL and preserving the existing SQLite database..."
  if ! command -v psql >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y postgresql postgresql-client
  fi
  systemctl enable --now postgresql
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='www-data') THEN
    CREATE ROLE "www-data" LOGIN;
  END IF;
END $$;
SQL
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='parenting_together'" | grep -q 1; then
    runuser -u postgres -- createdb --owner=www-data parenting_together
  fi
  NEW_DATABASE_URL='postgresql:///parenting_together?host=/var/run/postgresql&user=www-data'
  if [ -f "$DATABASE_PATH" ]; then
    python3 - "$DATABASE_PATH" "$BACKUPS/sqlite-$(date -u +%Y%m%dT%H%M%S)-$$.db" <<'PY'
import os, sqlite3, sys
source = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
os.chmod(sys.argv[2], 0o600)
PY
  fi
  # Do not change the live environment until every copied row has been verified.
  runuser -u www-data -- env DATABASE_URL="$NEW_DATABASE_URL" DATABASE_PATH="$DATABASE_PATH" \
    "$APP_DIR/.venv/bin/python" "$APP_DIR/migrate_sqlite.py"
  python3 - "$ENV_FILE" "$NEW_DATABASE_URL" <<'PY'
import os, shlex, sys
from pathlib import Path
path=Path(sys.argv[1]); stat=path.stat()
lines=[line for line in path.read_text().splitlines() if not line.startswith('DATABASE_URL=')]
lines.append('DATABASE_URL=' + shlex.quote(sys.argv[2]))
tmp=path.with_suffix('.env.pending')
tmp.write_text('\n'.join(lines) + '\n')
os.chmod(tmp, 0o640); os.chown(tmp, stat.st_uid, stat.st_gid)
os.replace(tmp, path)
PY
  echo "SQLite backup saved in $BACKUPS. PostgreSQL migration verified."
else
  # The Debian cluster wrapper can be inactive while an external DB is used.
  # Only start local PostgreSQL for the managed Unix-socket connection.
  if [[ "$DATABASE_URL" == *'/var/run/postgresql'* ]]; then
    systemctl enable --now postgresql
  fi
  BACKUP_FILE="$BACKUPS/postgres-$(date -u +%Y%m%d).sql.gz"
  if [ ! -s "$BACKUP_FILE" ]; then
    runuser -u www-data -- pg_dump "$DATABASE_URL" | gzip > "$BACKUP_FILE.pending"
    chmod 600 "$BACKUP_FILE.pending"
    mv "$BACKUP_FILE.pending" "$BACKUP_FILE"
  fi
  runuser -u www-data -- env DATABASE_URL="$DATABASE_URL" \
    "$APP_DIR/.venv/bin/python" -c "import sys; sys.path.insert(0, '$APP_DIR'); from database import initialize_postgres; initialize_postgres({'DATABASE_URL': __import__('os').environ['DATABASE_URL']})"
fi
