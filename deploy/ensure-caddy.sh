#!/usr/bin/env bash
set -euo pipefail
if command -v caddy >/dev/null 2>&1 && caddy version | python3 -c 'import re,sys; m=re.search(r"v?(\d+)\.(\d+)\.(\d+)",sys.stdin.read());sys.exit(0 if m and tuple(map(int,m.groups())) >= (2,10,1) else 1)'; then
  exit 0
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
systemctl stop nginx >/dev/null 2>&1 || true
apt-get install -y caddy
