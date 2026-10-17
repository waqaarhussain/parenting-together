#!/usr/bin/env bash
set -euo pipefail
SITE_URL="$(python3 -c 'import json; print(json.load(open("/etc/parenting-together-site.json"))["url"])')"
for _ in $(seq 1 12); do
  if curl -fsS --connect-timeout 5 --max-time 10 "$SITE_URL/health" >/dev/null; then
    echo "HTTPS ready: $SITE_URL"
    exit 0
  fi
  sleep 5
done
echo "HTTPS is not ready at $SITE_URL. Check that ports 80 and 443 are open in the VPS/provider firewall."
echo 'For a hostname, its A/AAAA records must point to this VPS. For IP mode, the selected public IP must reach this VPS directly.'
echo 'Caddy will keep retrying certificate issuance and renew certificates automatically.'
journalctl -u caddy -n 35 --no-pager || true
exit 1
