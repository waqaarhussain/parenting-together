#!/usr/bin/env bash
set -euo pipefail
# Reload after ExecStartPre: the first upgrade may just have added DATABASE_URL.
set -a
. /etc/parenting-together.env
set +a
exec /opt/parenting-together/.venv/bin/gunicorn \
  --workers 2 --worker-class gthread --threads 128 --timeout 90 --graceful-timeout 20 \
  --bind 127.0.0.1:8765 --access-logfile - --error-logfile - app:app
