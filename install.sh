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
apt-get install -y git nginx python3 python3-venv python3-pip ca-certificates curl openssl

if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  git fetch origin main
  git reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --depth 1 "$REPO" "$APP_DIR"
fi

mkdir -p "$DATA_DIR/uploads"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  SECRET="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<ENV
SECRET_KEY=$SECRET
DATABASE_PATH=$DATA_DIR/parenting.db
UPLOAD_DIR=$DATA_DIR/uploads
MAX_UPLOAD_MB=10
ENV
  chmod 640 "$ENV_FILE"
  chown root:www-data "$ENV_FILE"
fi

chown -R www-data:www-data "$APP_DIR" "$DATA_DIR"
install -m 644 "$APP_DIR/deploy/parenting-together.service" /etc/systemd/system/parenting-together.service
install -m 644 "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/parenting-together
ln -sfn /etc/nginx/sites-available/parenting-together /etc/nginx/sites-enabled/parenting-together
rm -f /etc/nginx/sites-enabled/default
install -m 755 "$APP_DIR/update-live.sh" /usr/local/bin/update-live

systemctl daemon-reload
systemctl enable --now parenting-together
nginx -t
systemctl enable --now nginx
systemctl reload nginx

sleep 1
if curl -fsS http://127.0.0.1:8765/health >/dev/null; then
  echo
  echo "Parenting Together installed successfully."
  echo "Open: http://$(hostname -I | awk '{print $1}')"
  echo "Future updates: update-live"
else
  echo "The service did not pass its local health check."
  systemctl --no-pager --full status parenting-together || true
  exit 1
fi
