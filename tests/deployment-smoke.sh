#!/usr/bin/env bash
# Destructive fixture setup, for a disposable GitHub Actions runner ONLY.
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ]; then
  echo 'This test is only for a disposable CI runner.' >&2
  exit 1
fi
APP_DIR=/opt/parenting-together
sudo mkdir -p "$APP_DIR" /var/lib/parenting-together/uploads
sudo cp -a . "$APP_DIR/"
sudo python3 -m venv "$APP_DIR/.venv"
sudo "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
sudo chown -R www-data:www-data /var/lib/parenting-together
sudo tee /etc/parenting-together.env >/dev/null <<'ENV'
SECRET_KEY=ci-deployment-only-not-a-real-secret
DATABASE_PATH=/var/lib/parenting-together/parenting.db
UPLOAD_DIR=/var/lib/parenting-together/uploads
COOKIE_SECURE=0
ENV
sudo chmod 640 /etc/parenting-together.env
sudo chown root:www-data /etc/parenting-together.env
cd "$APP_DIR"
sudo -u www-data env DATABASE_PATH=/var/lib/parenting-together/parenting.db UPLOAD_DIR=/var/lib/parenting-together/uploads "$APP_DIR/.venv/bin/python" - <<'PY'
from app import app
client=app.test_client()
account=client.post('/api/auth/register', json={'name':'Upgrade Parent','email':'upgrade@example.test',
    'password':'test-password-123','timezone_name':'Europe/London','calendar_color':'#8a74ff'})
assert account.status_code==201,account.data
message=client.post('/api/messages',json={'body':'pt1:encrypted:upgrade-test'},headers={'X-CSRF-Token':account.json['csrf']})
assert message.status_code==201,message.data
PY
sudo cp deploy/parenting-together.service /etc/systemd/system/parenting-together.service
sudo systemctl daemon-reload
sudo systemctl start parenting-together
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8765/health >/tmp/parenting-health.json; then break; fi
  sleep 1
done
sudo -u www-data /bin/bash -c 'set -a; . /etc/parenting-together.env; set +a; /opt/parenting-together/.venv/bin/python -' <<'PY'
import json,os
from app import app,db
assert os.environ['SECRET_KEY']=='ci-deployment-only-not-a-real-secret'
assert app.config['DATABASE_URL']
with db() as conn:
    assert conn.execute('SELECT body FROM messages').fetchone()[0]=='pt1:encrypted:upgrade-test'
client=app.test_client()
login=client.post('/api/auth/login',json={'identifier':'upgrade@example.test','password':'test-password-123'})
assert login.status_code==200,login.data
assert client.get('/api/messages/verify').json['verified']
assert json.load(open('/tmp/parenting-health.json'))['database']=='postgresql'
print('Automatic startup migration, shell-safe DSN, ciphertext and login verified.')
PY
"$APP_DIR/.venv/bin/python" - <<'PYHTTP'
import http.cookiejar,json,urllib.request
base='http://127.0.0.1:8765'
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def post(path,payload,csrf=None):
    headers={'Content-Type':'application/json'}
    if csrf:headers['X-CSRF-Token']=csrf
    with opener.open(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=headers),timeout=15) as response:
        return json.load(response)
account=post('/api/auth/login',{'identifier':'upgrade@example.test','password':'test-password-123'})
with opener.open(base+'/api/live',timeout=15) as stream:
    assert 'text/event-stream' in stream.headers['Content-Type']
    assert stream.readline()==b'retry: 5000\n'
    assert stream.readline()==b'event: ready\n'
    ready=json.loads(stream.readline().decode().removeprefix('data: '))
    assert ready['version']
    post('/api/messages',{'body':'pt1:live:network-test'},account['csrf'])
    while True:
        line=stream.readline()
        if line.startswith(b'event: change'):break
        assert line, 'stream unexpectedly closed'
    data=json.loads(stream.readline().decode().removeprefix('data: '))
    assert 'tables' in data
    assert 'body' not in data
print('Real Gunicorn HTTP stream delivered a change without exposing message text.')
PYHTTP
sudo test -n "$(sudo find /var/backups/parenting-together -name 'sqlite-*.db' -print -quit)"
# Repeated starts must not copy SQLite again or duplicate any records.
sudo systemctl restart parenting-together
sleep 2
curl -fsS http://127.0.0.1:8765/health
printf 'RESET\n' | sudo bash reset-parenting-together.sh
sudo -u www-data /bin/bash -c 'set -a; . /etc/parenting-together.env; set +a; /opt/parenting-together/.venv/bin/python -' <<'PY'
from app import db
with db() as conn:
    assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==0
print('PostgreSQL reset helper verified.')
PY
sudo systemctl stop parenting-together
