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
git -c safe.directory="$APP_DIR" fetch origin main
git -c safe.directory="$APP_DIR" reset --hard origin/main

"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r requirements.txt
git -c safe.directory="$APP_DIR" rev-parse HEAD > "$APP_DIR/.deploy-version"
chmod 644 "$APP_DIR/.deploy-version"
chown -R root:root "$APP_DIR"

install -m 644 deploy/parenting-together.service /etc/systemd/system/parenting-together.service
install -m 755 update-live.sh /usr/local/bin/update-live
install -m 755 reset-parenting-together.sh /usr/local/bin/reset-parenting-together

if ! command -v caddy >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  systemctl stop nginx >/dev/null 2>&1 || true
  apt-get install -y caddy
fi
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
rm -f /etc/systemd/system/caddy.service.d/parenting-together.conf
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  systemctl stop caddy >/dev/null 2>&1 || true
  systemctl start nginx >/dev/null 2>&1 || true
  exit 1
fi

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

echo
echo "Updated to: $(git rev-parse --short HEAD)"
echo "Parenting Together is live."
echo "HTTPS: https://v2202603253680444276.megasrv.de"
