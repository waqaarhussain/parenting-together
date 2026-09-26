#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

REPO="https://github.com/waqaarhussain/parenting-together.git"
APP_DIR="/opt/parenting-together"
DATA_DIR="/var/lib/parenting-together"
ENV_FILE="/etc/parenting-together.env"

echo "Installing Parenting Together..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3 python3-venv python3-pip ca-certificates curl openssl

if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  git -c safe.directory="$APP_DIR" fetch origin main
  git -c safe.directory="$APP_DIR" reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --depth 1 "$REPO" "$APP_DIR"
fi

mkdir -p "$DATA_DIR/uploads"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
git -C "$APP_DIR" -c safe.directory="$APP_DIR" rev-parse HEAD > "$APP_DIR/.deploy-version"
chmod 644 "$APP_DIR/.deploy-version"

if [ ! -f "$ENV_FILE" ]; then
  SECRET="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<ENV
SECRET_KEY=$SECRET
DATABASE_PATH=$DATA_DIR/parenting.db
UPLOAD_DIR=$DATA_DIR/uploads
MAX_UPLOAD_MB=10
PARENTING_DOMAIN=v2202603253680444276.megasrv.de
ENV
  chmod 640 "$ENV_FILE"
  chown root:www-data "$ENV_FILE"
fi

chown -R root:root "$APP_DIR"
chown -R www-data:www-data "$DATA_DIR"
install -m 644 "$APP_DIR/deploy/parenting-together.service" /etc/systemd/system/parenting-together.service
install -m 755 "$APP_DIR/update-live.sh" /usr/local/bin/update-live
install -m 755 "$APP_DIR/reset-parenting-together.sh" /usr/local/bin/reset-parenting-together

if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  systemctl stop nginx >/dev/null 2>&1 || true
  apt-get install -y caddy
fi
install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
install -m 644 "$APP_DIR/deploy/caddy-parenting-together.conf" /etc/systemd/system/caddy.service.d/parenting-together.conf
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  systemctl stop caddy >/dev/null 2>&1 || true
  systemctl start nginx >/dev/null 2>&1 || true
  exit 1
fi

systemctl daemon-reload
systemctl enable --now parenting-together
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

sleep 1
if curl -fsS http://127.0.0.1:8765/health >/dev/null; then
  echo
  echo "Parenting Together installed successfully."
  echo "Open: http://$(hostname -I | awk '{print $1}')"
  echo "Future updates: update-live"
  echo "Full data reset: reset-parenting-together"
else
  echo "The service did not pass its local health check."
  systemctl --no-pager --full status parenting-together || true
  exit 1
fi
