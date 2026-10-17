#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

APP_DIR="/opt/parenting-together"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Parenting Together is not installed. Run the fresh installer first."
  exit 1
fi

echo "Updating Parenting Together..."
cd "$APP_DIR"
if [ "${1:-}" != "--pulled" ]; then
  git -c safe.directory="$APP_DIR" fetch origin main
  git -c safe.directory="$APP_DIR" reset --hard origin/main
  exec /bin/bash "$APP_DIR/update-live.sh" --pulled
fi

"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r requirements.txt
git -c safe.directory="$APP_DIR" rev-parse HEAD > "$APP_DIR/.deploy-version"
chmod 644 "$APP_DIR/.deploy-version"
chown -R root:root "$APP_DIR"

install -m 644 deploy/parenting-together.service /etc/systemd/system/parenting-together.service
install -m 755 update-live.sh /usr/local/bin/update-live
install -m 755 reset-parenting-together.sh /usr/local/bin/reset-parenting-together

bash "$APP_DIR/deploy/ensure-caddy.sh"
python3 "$APP_DIR/deploy/configure_site.py" --reuse
install -m 755 "$APP_DIR/deploy/configure-site.sh" /usr/local/bin/configure-parenting-together
SITE_URL="$(python3 -c 'import json; print(json.load(open("/etc/parenting-together-site.json"))["url"])')"

systemctl daemon-reload
systemctl restart parenting-together
systemctl stop nginx >/dev/null 2>&1 || true
systemctl enable --now caddy
if ! systemctl restart caddy; then
  systemctl stop caddy >/dev/null 2>&1 || true
  systemctl start nginx >/dev/null 2>&1 || true
  exit 1
fi
systemctl disable nginx >/dev/null 2>&1 || true
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

bash "$APP_DIR/deploy/check-site.sh"

echo
echo "Updated to: $(git rev-parse --short HEAD)"
echo "Parenting Together is live."
echo "HTTPS: $SITE_URL"
