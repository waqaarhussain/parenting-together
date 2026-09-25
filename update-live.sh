#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

APP_DIR="/opt/parenting-together"
REPO="https://github.com/waqaarhussain/parenting-together.git"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Parenting Together is not installed. Run the fresh installer first."
  exit 1
fi

echo "Updating Parenting Together..."
cd "$APP_DIR"
git fetch origin main
git reset --hard origin/main

"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r requirements.txt
chown -R www-data:www-data "$APP_DIR"

install -m 644 deploy/parenting-together.service /etc/systemd/system/parenting-together.service
install -m 644 deploy/nginx.conf /etc/nginx/sites-available/parenting-together
ln -sfn /etc/nginx/sites-available/parenting-together /etc/nginx/sites-enabled/parenting-together
rm -f /etc/nginx/sites-enabled/default
install -m 755 update-live.sh /usr/local/bin/update-live

systemctl daemon-reload
nginx -t
systemctl restart parenting-together
systemctl reload nginx

echo
echo "Updated to: $(git rev-parse --short HEAD)"
echo "Parenting Together is live."
