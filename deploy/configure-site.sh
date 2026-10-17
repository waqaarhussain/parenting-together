#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then exec sudo /bin/bash "$0" "$@"; fi
APP_DIR=/opt/parenting-together
python3 "$APP_DIR/deploy/configure_site.py" --prompt
systemctl restart caddy
SITE_URL="$(python3 -c 'import json; print(json.load(open("/etc/parenting-together-site.json"))["url"])')"
echo "Open: $SITE_URL"
echo 'Caddy will obtain and renew the certificate automatically. Ports 80 and 443 must be reachable.'
bash "$APP_DIR/deploy/check-site.sh"
