#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

DATA_DIR="/var/lib/parenting-together"
ENV_FILE="/etc/parenting-together.env"
SERVICE="parenting-together"

echo "This permanently deletes all Parenting Together data:"
echo "accounts, families, children, messages, calendar events, handovers,"
echo "decisions, expenses, receipts, rules and evidence records."
echo
read -r -p "Type RESET to continue: " CONFIRMATION

if [ "$CONFIRMATION" != "RESET" ]; then
  echo "Reset cancelled. Nothing was deleted."
  exit 0
fi

systemctl stop "$SERVICE"

python3 - "$DATA_DIR" "$ENV_FILE" <<'PY'
from pathlib import Path
import secrets
import shutil
import sys

data_dir = Path(sys.argv[1]).resolve()
env_file = Path(sys.argv[2]).resolve()
expected = Path("/var/lib/parenting-together")
expected_env = Path("/etc/parenting-together.env")
if data_dir != expected or env_file != expected_env:
    raise SystemExit("Refusing to reset unexpected paths")
if not env_file.exists():
    raise SystemExit("Environment file is missing; reset cancelled")

for name in ("parenting.db", "parenting.db-wal", "parenting.db-shm"):
    (data_dir / name).unlink(missing_ok=True)

uploads = data_dir / "uploads"
if uploads.exists():
    for item in uploads.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
uploads.mkdir(parents=True, exist_ok=True)

lines = env_file.read_text().splitlines()
replacement = "SECRET_KEY=" + secrets.token_hex(32)
updated = False
for index, line in enumerate(lines):
    if line.startswith("SECRET_KEY="):
        lines[index] = replacement
        updated = True
        break
if not updated:
    lines.insert(0, replacement)
env_file.write_text("\n".join(lines) + "\n")
PY

chown -R www-data:www-data "$DATA_DIR"
chmod 640 "$ENV_FILE"
chown root:www-data "$ENV_FILE"
systemctl start "$SERVICE"

sleep 1
if curl -fsS http://127.0.0.1:8765/health >/dev/null; then
  echo
  echo "Parenting Together has been reset."
  echo "Open the app and create the first account."
else
  echo "The data was reset, but the service did not pass its health check."
  systemctl --no-pager --full status "$SERVICE" || true
  exit 1
fi
