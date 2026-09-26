import hashlib
import html
import io
import json
import os
import secrets
import sqlite3
import time
import calendar as month_calendar
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, session
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["DATABASE_PATH"] = os.environ.get("DATABASE_PATH", str(Path(__file__).with_name("parenting.db")))
app.config["UPLOAD_DIR"] = os.environ.get("UPLOAD_DIR", str(Path(__file__).with_name("uploads")))
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "1") == "1"


def deployed_version():
    configured = os.environ.get("APP_VERSION", "").strip()
    if configured:
        return configured
    root = Path(__file__).resolve().parent
    candidates = [root / ".deploy-version", root / ".git" / "refs" / "remotes" / "origin" / "main"]
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            candidates.append(root / ".git" / head[5:])
    except OSError:
        pass
    for candidate in candidates:
        try:
            value = candidate.read_text().strip()
            if value:
                return value[:40]
        except OSError:
            continue
    return str(Path(__file__).stat().st_mtime_ns)


app.config["APP_VERSION"] = deployed_version()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf", "ptenc"}

Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db():
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_vaults (
        user_id INTEGER PRIMARY KEY,
        envelope_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS families (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER NOT NULL,
        invite_code TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS family_members (
        family_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'parent',
        joined_at TEXT NOT NULL,
        PRIMARY KEY(family_id, user_id),
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        birthday TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        record_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS message_reads (
        message_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        read_at TEXT NOT NULL,
        PRIMARY KEY(message_id, user_id),
        FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS typing_status (
        family_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        PRIMARY KEY(family_id, user_id),
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS messages_family_id_idx ON messages(family_id, id);
    CREATE INDEX IF NOT EXISTS message_reads_user_idx ON message_reads(user_id, message_id);
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        start_at TEXT NOT NULL,
        end_at TEXT,
        notes TEXT,
        reminder_minutes INTEGER NOT NULL DEFAULT 0,
        recurrence TEXT NOT NULL DEFAULT 'none',
        recurrence_until TEXT,
        timezone_offset INTEGER NOT NULL DEFAULT 0,
        cancelled_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS handovers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        location TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        response_note TEXT,
        completed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        details TEXT,
        deadline TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        response_note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        amount_pence INTEGER NOT NULL,
        split_percent INTEGER NOT NULL DEFAULT 50,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        receipt_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        rule_type TEXT NOT NULL DEFAULT 'custom',
        value_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        user_id INTEGER,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        summary TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        actor_id INTEGER,
        notification_type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        target_type TEXT,
        target_id INTEGER,
        target_value TEXT,
        dedupe_key TEXT,
        created_at TEXT NOT NULL,
        read_at TEXT,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(actor_id) REFERENCES users(id),
        UNIQUE(user_id, dedupe_key)
    );
    CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications(user_id, read_at, id);
    CREATE TABLE IF NOT EXISTS feature_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS feature_requests_created_idx ON feature_requests(created_at, id);
    CREATE TRIGGER IF NOT EXISTS messages_no_update
    BEFORE UPDATE ON messages
    BEGIN
        SELECT RAISE(ABORT, 'Message records are immutable');
    END;
    CREATE TRIGGER IF NOT EXISTS messages_no_delete
    BEFORE DELETE ON messages
    BEGIN
        SELECT RAISE(ABORT, 'Message records are immutable');
    END;
    CREATE TRIGGER IF NOT EXISTS audit_no_update
    BEFORE UPDATE ON audit
    BEGIN
        SELECT RAISE(ABORT, 'Audit records are immutable');
    END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete
    BEFORE DELETE ON audit
    BEGIN
        SELECT RAISE(ABORT, 'Audit records are immutable');
    END;
    """
    with db() as conn:
        conn.executescript(schema)
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "username" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_idx ON users(username COLLATE NOCASE) WHERE username IS NOT NULL")
        for user in conn.execute("SELECT id,email FROM users WHERE username IS NULL OR username='' ORDER BY id"):
            base = (user["email"].split("@", 1)[0] if "@" in user["email"] else "parent")[:24]
            base = "".join(ch for ch in base if ch.isalnum() or ch in "._-") or "parent"
            candidate = base
            suffix = 1
            while conn.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE AND id<>?", (candidate, user["id"])).fetchone():
                suffix += 1
                candidate = (base[:24] + str(suffix))[:30]
            conn.execute("UPDATE users SET username=? WHERE id=?", (candidate, user["id"]))
        event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        migrations = {
            "reminder_minutes": "INTEGER NOT NULL DEFAULT 0",
            "recurrence": "TEXT NOT NULL DEFAULT 'none'",
            "recurrence_until": "TEXT",
            "timezone_offset": "INTEGER NOT NULL DEFAULT 0",
            "cancelled_at": "TEXT",
            "updated_at": "TEXT",
        }
        for name, definition in migrations.items():
            if name not in event_columns:
                conn.execute("ALTER TABLE events ADD COLUMN " + name + " " + definition)
        conn.execute("UPDATE events SET updated_at=created_at WHERE updated_at IS NULL")


init_db()


def rowdict(row):
    return dict(row) if row else None


def parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def add_month(value, preferred_day=None):
    month = value.month + 1
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(preferred_day or value.day, month_calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def expand_event(row, range_start=None, range_end=None, limit=2000):
    item = rowdict(row)
    if item.get("cancelled_at"):
        return []
    start = parse_datetime(item["start_at"])
    end = parse_datetime(item.get("end_at"))
    duration = end - start if end else None
    repeat = item.get("recurrence") or "none"
    until = parse_datetime(item.get("recurrence_until"))
    if item.get("recurrence_until") and len(str(item["recurrence_until"])) == 10:
        until = until.replace(hour=23, minute=59, second=59)
    if repeat == "none":
        until = start
    occurrences = []
    current = start
    for _ in range(limit):
        if until and current > until:
            break
        if (range_start is None or current >= range_start) and (range_end is None or current <= range_end):
            occurrence = dict(item)
            occurrence["series_start_at"] = item["start_at"]
            occurrence["series_end_at"] = item.get("end_at")
            occurrence["start_at"] = current.isoformat(timespec="minutes")
            occurrence["end_at"] = (current + duration).isoformat(timespec="minutes") if duration else None
            occurrence["occurrence_key"] = str(item["id"]) + ":" + occurrence["start_at"]
            occurrence["is_recurring"] = repeat != "none"
            occurrences.append(occurrence)
        if repeat == "daily":
            current += timedelta(days=1)
        elif repeat == "weekly":
            current += timedelta(days=7)
        elif repeat == "monthly":
            current = add_month(current, start.day)
        else:
            break
        if range_end and current > range_end:
            break
    return occurrences


def csrf_token():
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["csrf"] = token
    return token


def require_csrf(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or supplied != session.get("csrf"):
            return jsonify({"error": "Security token expired. Refresh and try again."}), 403
        return fn(*args, **kwargs)
    return wrapped


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Sign in required"}), 401
        return fn(*args, **kwargs)
    return wrapped


def family_id_for(user_id):
    with db() as conn:
        row = conn.execute(
            "SELECT family_id FROM family_members WHERE user_id=? ORDER BY joined_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row["family_id"] if row else None


def require_family():
    fid = family_id_for(session["user_id"])
    if not fid:
        return None
    return fid


def family_uses_vault(conn, fid):
    return bool(conn.execute(
        """SELECT 1 FROM family_members fm JOIN user_vaults uv ON uv.user_id=fm.user_id
           WHERE fm.family_id=? LIMIT 1""", (fid,)
    ).fetchone())


def audit_event(conn, fid, uid, event_type, entity_type, entity_id, summary, metadata=None):
    conn.execute(
        "INSERT INTO audit(family_id,user_id,event_type,entity_type,entity_id,summary,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (fid, uid, event_type, entity_type, entity_id, summary, json.dumps(metadata or {}), now_iso()),
    )


def notify_family(conn, fid, actor_id, notification_type, title, body="", target_type=None,
                  target_id=None, target_value=None, include_actor=False, dedupe_key=None):
    members = conn.execute("SELECT user_id FROM family_members WHERE family_id=?", (fid,)).fetchall()
    stamp = now_iso()
    for member in members:
        if not include_actor and member["user_id"] == actor_id:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO notifications(
                   family_id,user_id,actor_id,notification_type,title,body,target_type,target_id,
                   target_value,dedupe_key,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, member["user_id"], actor_id, notification_type, title, body, target_type,
             target_id, target_value, dedupe_key, stamp),
        )


def materialize_event_reminders(conn, fid, uid):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    events = conn.execute(
        """SELECT e.*,u.name creator_name FROM events e JOIN users u ON u.id=e.creator_id
           WHERE e.family_id=? AND e.cancelled_at IS NULL AND e.reminder_minutes>0""",
        (fid,),
    ).fetchall()
    for event in events:
        reminder_minutes = max(0, min(int(event["reminder_minutes"] or 0), 10080))
        for occurrence in expand_event(event, now - timedelta(days=8), now + timedelta(days=370)):
            local_start = parse_datetime(occurrence["start_at"])
            utc_start = local_start + timedelta(minutes=int(occurrence.get("timezone_offset") or 0))
            remind_at = utc_start - timedelta(minutes=reminder_minutes)
            if remind_at <= now < utc_start:
                key = "event-reminder:" + occurrence["occurrence_key"]
                conn.execute(
                    """INSERT OR IGNORE INTO notifications(
                           family_id,user_id,actor_id,notification_type,title,body,target_type,
                           target_id,target_value,dedupe_key,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (fid, uid, event["creator_id"], "event_reminder", "Event reminder",
                     event["title"],
                     "event", event["id"], occurrence["start_at"], key, now_iso()),
                )
                break


@app.get("/api/notifications")
@login_required
def list_notifications():
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        materialize_event_reminders(conn, fid, uid)
        rows = conn.execute(
            "SELECT * FROM notifications WHERE family_id=? AND user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 100",
            (fid, uid),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE family_id=? AND user_id=? AND read_at IS NULL",
            (fid, uid),
        ).fetchone()[0]
    return jsonify({"unread": unread, "items": [rowdict(row) for row in rows]})


@app.post("/api/notifications/read")
@login_required
@require_csrf
def read_notifications():
    data = request.get_json(silent=True) or {}
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        if data.get("id"):
            conn.execute(
                "UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND family_id=? AND user_id=?",
                (stamp, int(data["id"]), fid, uid),
            )
        else:
            conn.execute(
                "UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE family_id=? AND user_id=?",
                (stamp, fid, uid),
            )
    return jsonify({"ok": True})


def unique_invite_code(conn):
    for _ in range(20):
        code = secrets.token_urlsafe(24)
        if not conn.execute("SELECT 1 FROM families WHERE invite_code=?", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate invite code")


def me_payload(uid):
    with db() as conn:
        user = conn.execute("SELECT id,name,username,email,created_at FROM users WHERE id=?", (uid,)).fetchone()
        vault = conn.execute("SELECT envelope_json FROM user_vaults WHERE user_id=?", (uid,)).fetchone()
        fid = family_id_for(uid)
        family = None
        members = []
        children = []
        family_vault_ready = False
        if fid:
            family = conn.execute("SELECT id,name,invite_code,created_at FROM families WHERE id=?", (fid,)).fetchone()
            members = conn.execute(
                "SELECT u.id,u.name,u.username,u.email,fm.role,fm.joined_at FROM family_members fm JOIN users u ON u.id=fm.user_id WHERE fm.family_id=? ORDER BY fm.joined_at",
                (fid,),
            ).fetchall()
            children = conn.execute("SELECT * FROM children WHERE family_id=? ORDER BY name", (fid,)).fetchall()
            family_vault_ready = bool(conn.execute(
                """SELECT 1 FROM family_members fm JOIN user_vaults uv ON uv.user_id=fm.user_id
                   WHERE fm.family_id=? LIMIT 1""", (fid,)
            ).fetchone())
    return {
        "user": rowdict(user),
        "family": rowdict(family),
        "members": [rowdict(x) for x in members],
        "children": [rowdict(x) for x in children],
        "vault_envelope": json.loads(vault["envelope_json"]) if vault else None,
        "family_vault_ready": family_vault_ready,
        "csrf": csrf_token(),
    }


@app.get("/")
def index():
    response = app.make_response(render_template("index.html", app_version=app.config["APP_VERSION"]))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/api/version")
def api_version():
    response = jsonify({"version": app.config["APP_VERSION"]})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/health")
def health():
    return jsonify({"ok": True, "time": now_iso()})


@app.get("/api/me")
def api_me():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"authenticated": False, "csrf": csrf_token()})
    return jsonify({"authenticated": True, **me_payload(uid)})


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    valid_username = 3 <= len(username) <= 30 and all(ch.isalnum() or ch in "._-" for ch in username)
    valid_email = bool(email) and "@" in email and len(email) <= 254
    if len(name) < 2 or (not valid_username and not valid_email) or len(password) < 8:
        return jsonify({"error": "Use your name, a username or email, and a password of at least 8 characters."}), 400
    if not username:
        username = email.split("@", 1)[0][:30]
        if len(username) < 3 or not all(ch.isalnum() or ch in "._-" for ch in username):
            username = "parent" + secrets.token_hex(3)
    if not email:
        email = "local-" + secrets.token_hex(16) + "@account.invalid"
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(name,email,username,password_hash,created_at) VALUES(?,?,?,?,?)",
                (name, email, username, generate_password_hash(password), now_iso()),
            )
            uid = cur.lastrowid
            code = unique_invite_code(conn)
            fam = conn.execute(
                "INSERT INTO families(name,owner_id,invite_code,created_at) VALUES(?,?,?,?)",
                ("Our family", uid, code, now_iso()),
            )
            fid = fam.lastrowid
            conn.execute(
                "INSERT INTO family_members(family_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                (fid, uid, "parent", now_iso()),
            )
            if valid_vault_envelope(data.get("vault_envelope")):
                stamp = now_iso()
                conn.execute(
                    "INSERT INTO user_vaults(user_id,envelope_json,created_at,updated_at) VALUES(?,?,?,?)",
                    (uid, json.dumps(data["vault_envelope"], separators=(",", ":")), stamp, stamp),
                )
            audit_event(conn, fid, uid, "created", "family", fid, "Created family space")
    except sqlite3.IntegrityError:
        return jsonify({"error": "That username or email is already in use."}), 409
    session.clear()
    session["user_id"] = uid
    csrf_token()
    return jsonify(me_payload(uid)), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or data.get("email") or "").strip().lower()
    password = data.get("password", "")
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE OR username=? COLLATE NOCASE", (identifier, identifier)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Username, email or password is incorrect."}), 401
    session.clear()
    session["user_id"] = user["id"]
    csrf_token()
    return jsonify(me_payload(user["id"]))


@app.post("/api/auth/logout")
@login_required
@require_csrf
def logout():
    session.clear()
    return jsonify({"ok": True})


VAULT_FIELDS = {
    "children": {"name", "birthday"},
    "messages": {"body"},
    "events": {"title", "notes"},
    "handovers": {"title", "location", "response_note"},
    "decisions": {"title", "details", "response_note"},
    "expenses": {"title"},
    "rules": {"title", "value_text"},
    "audit": {"summary", "metadata_json"},
    "notifications": {"title", "body"},
}


def valid_vault_envelope(value):
    return (isinstance(value, dict) and value.get("v") == 1
            and all(isinstance(value.get(key), str) and value.get(key)
                    for key in ("salt", "iv", "data")))


@app.post("/api/vault/setup")
@login_required
@require_csrf
def setup_vault():
    """Save a recovery-wrapped family key and atomically encrypt legacy text fields."""
    data = request.get_json(silent=True) or {}
    envelope = data.get("envelope")
    records = data.get("records") or []
    if not valid_vault_envelope(envelope):
        return jsonify({"error": "Invalid encrypted vault envelope."}), 400
    if not isinstance(records, list) or len(records) > 5000:
        return jsonify({"error": "Invalid vault migration."}), 400
    prepared = []
    for record in records:
        table = record.get("table") if isinstance(record, dict) else None
        item_id = record.get("id") if isinstance(record, dict) else None
        values = record.get("values") if isinstance(record, dict) else None
        if table not in VAULT_FIELDS or not isinstance(item_id, int) or not isinstance(values, dict):
            return jsonify({"error": "Invalid vault migration record."}), 400
        keys = list(values)
        if not keys or any(key not in VAULT_FIELDS[table] for key in keys):
            return jsonify({"error": "Invalid encrypted field."}), 400
        if any(value is not None and (not isinstance(value, str) or not value.startswith("pt1:")) for value in values.values()):
            return jsonify({"error": "Vault migration contains unencrypted text."}), 400
        prepared.append((table, item_id, values, keys))
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TRIGGER IF EXISTS messages_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        for table, item_id, values, keys in prepared:
            assignments = ",".join(key + "=?" for key in keys)
            params = [values[key] for key in keys] + [item_id, fid]
            plaintext_only = " AND ".join("(" + key + " IS NULL OR " + key + " NOT LIKE 'pt1:%')" for key in keys)
            conn.execute("UPDATE " + table + " SET " + assignments + " WHERE id=? AND family_id=? AND " + plaintext_only, params)
        conn.execute("""CREATE TRIGGER messages_no_update BEFORE UPDATE ON messages
                        BEGIN SELECT RAISE(ABORT, 'Message records are secure'); END""")
        conn.execute("""CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
                        BEGIN SELECT RAISE(ABORT, 'Audit records are secure'); END""")
        conn.execute(
            """INSERT INTO user_vaults(user_id,envelope_json,created_at,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET envelope_json=excluded.envelope_json,updated_at=excluded.updated_at""",
            (uid, json.dumps(envelope, separators=(",", ":")), stamp, stamp),
        )
    return jsonify({"ok": True, "vault_envelope": envelope})


@app.get("/api/vault/legacy")
@login_required
def vault_legacy():
    fid = require_family()
    payload = []
    with db() as conn:
        for table, fields in VAULT_FIELDS.items():
            columns = ["id"] + sorted(fields)
            rows = conn.execute(
                "SELECT " + ",".join(columns) + " FROM " + table + " WHERE family_id=? ORDER BY id", (fid,)
            ).fetchall()
            for row in rows:
                values = {field: row[field] for field in fields
                          if row[field] is not None and not str(row[field]).startswith("pt1:")}
                if values:
                    payload.append({"table": table, "id": row["id"], "values": values})
    return jsonify(payload)


@app.post("/api/family/join")
@login_required
@require_csrf
def join_family():
    data = request.get_json(silent=True) or {}
    code = data.get("invite_code", "").strip()
    uid = session["user_id"]
    envelope = data.get("envelope")
    if not code:
        return jsonify({"error": "Enter an invite code."}), 400
    with db() as conn:
        target = conn.execute("SELECT * FROM families WHERE invite_code=? COLLATE NOCASE", (code,)).fetchone()
        if not target:
            return jsonify({"error": "Invite code not found."}), 404
        target_uses_vault = bool(conn.execute(
            """SELECT 1 FROM family_members fm JOIN user_vaults uv ON uv.user_id=fm.user_id
               WHERE fm.family_id=? LIMIT 1""", (target["id"],)
        ).fetchone())
        if target_uses_vault and not valid_vault_envelope(envelope):
            return jsonify({"error": "Open the full secure invite link. A code alone cannot unlock this family."}), 400
        if conn.execute("SELECT 1 FROM family_members WHERE family_id=? AND user_id=?", (target["id"], uid)).fetchone():
            if valid_vault_envelope(envelope):
                stamp = now_iso()
                conn.execute(
                    """INSERT INTO user_vaults(user_id,envelope_json,created_at,updated_at) VALUES(?,?,?,?)
                       ON CONFLICT(user_id) DO UPDATE SET envelope_json=excluded.envelope_json,updated_at=excluded.updated_at""",
                    (uid, json.dumps(envelope, separators=(",", ":")), stamp, stamp),
                )
            return jsonify(me_payload(uid))
        if conn.execute("SELECT COUNT(*) c FROM family_members WHERE family_id=?", (target["id"],)).fetchone()["c"] >= 2:
            return jsonify({"error": "This family space already has two parents."}), 409
        current = family_id_for(uid)
        if current:
            member_count = conn.execute("SELECT COUNT(*) c FROM family_members WHERE family_id=?", (current,)).fetchone()["c"]
            activity_count = 0
            for table in ("messages", "events", "handovers", "decisions", "expenses", "children", "rules"):
                activity_count += conn.execute("SELECT COUNT(*) c FROM " + table + " WHERE family_id=?", (current,)).fetchone()["c"]
            if member_count == 1 and activity_count == 0:
                audit_event(conn, current, uid, "left", "family", current, "Left empty starter family space")
                conn.execute("DELETE FROM family_members WHERE family_id=? AND user_id=?", (current, uid))
            else:
                return jsonify({"error": "This account has records in its own family space. Joining would leave those records behind, so it was blocked."}), 409
        conn.execute(
            "INSERT INTO family_members(family_id,user_id,role,joined_at) VALUES(?,?,?,?)",
            (target["id"], uid, "parent", now_iso()),
        )
        if valid_vault_envelope(envelope):
            stamp = now_iso()
            conn.execute(
                """INSERT INTO user_vaults(user_id,envelope_json,created_at,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET envelope_json=excluded.envelope_json,updated_at=excluded.updated_at""",
                (uid, json.dumps(envelope, separators=(",", ":")), stamp, stamp),
            )
        conn.execute("UPDATE families SET invite_code=? WHERE id=?", (unique_invite_code(conn), target["id"]))
        audit_event(conn, target["id"], uid, "joined", "family", target["id"], "Joined family space")
        joining_user = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
        notify_family(conn, target["id"], uid, "family_joined", "Co-parent connected",
                      joining_user["name"] + " joined your family space", "home", target["id"])
    return jsonify(me_payload(uid))


@app.post("/api/feature-requests")
@login_required
@require_csrf
def create_feature_request():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not body:
        return jsonify({"error": "Type your feature request first."}), 400
    if len(body) > 100:
        return jsonify({"error": "Feature requests are limited to 100 characters."}), 400
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO feature_requests(family_id,user_id,body,created_at) VALUES(?,?,?,?)",
            (require_family(), session["user_id"], body, now_iso()),
        )
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.post("/api/children")
@login_required
@require_csrf
def add_child():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    birthday = data.get("birthday") or None
    if not name:
        return jsonify({"error": "Child name is required."}), 400
    fid = require_family()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO children(family_id,name,birthday,created_at) VALUES(?,?,?,?)",
            (fid, name, birthday, now_iso()),
        )
        audit_event(conn, fid, session["user_id"], "created", "child", cur.lastrowid, "Added child profile")
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.get("/api/messages")
@login_required
def list_messages():
    fid = require_family()
    uid = session["user_id"]
    try:
        before = int(request.args["before"]) if "before" in request.args else None
        after = int(request.args["after"]) if "after" in request.args else None
        around = int(request.args["around"]) if "around" in request.args else None
    except ValueError:
        return jsonify({"error": "Invalid message cursor."}), 400
    cursors = sum(value is not None for value in (before, after, around))
    if ((before is not None and before <= 0) or (after is not None and after < 0)
            or (around is not None and around <= 0) or cursors > 1):
        return jsonify({"error": "Invalid message cursor."}), 400
    message_select = """
        SELECT m.*,u.name sender_name,
               (SELECT MIN(read_at) FROM message_reads mr WHERE mr.message_id=m.id AND mr.user_id<>m.sender_id) read_at
        FROM messages m JOIN users u ON u.id=m.sender_id
    """
    if around is not None:
        with db() as conn:
            if not conn.execute("SELECT 1 FROM messages WHERE id=? AND family_id=?", (around, fid)).fetchone():
                return jsonify({"error": "Message not found."}), 404
            older = conn.execute(
                message_select + " WHERE m.family_id=? AND m.id<=? ORDER BY m.id DESC LIMIT 25",
                (fid, around),
            ).fetchall()
            newer = conn.execute(
                message_select + " WHERE m.family_id=? AND m.id>? ORDER BY m.id ASC LIMIT 25",
                (fid, around),
            ).fetchall()
            rows = list(reversed(older)) + list(newer)
            unread = [row["id"] for row in rows if row["sender_id"] != uid]
            if unread:
                stamp = now_iso()
                conn.executemany(
                    "INSERT OR IGNORE INTO message_reads(message_id,user_id,read_at) VALUES(?,?,?)",
                    [(mid, uid, stamp) for mid in unread],
                )
            has_older = bool(rows and conn.execute(
                "SELECT 1 FROM messages WHERE family_id=? AND id<? LIMIT 1", (fid, rows[0]["id"])
            ).fetchone())
            has_newer = bool(rows and conn.execute(
                "SELECT 1 FROM messages WHERE family_id=? AND id>? LIMIT 1", (fid, rows[-1]["id"])
            ).fetchone())
        return jsonify({"messages": [rowdict(row) for row in rows], "has_older": has_older,
                        "has_newer": has_newer, "target_id": around})
    where = "m.family_id=?"
    params = [fid]
    if before is not None:
        where += " AND m.id<?"
        params.append(before)
    if after is not None:
        where += " AND m.id>?"
        params.append(after)
    order = "ASC" if after is not None else "DESC"
    with db() as conn:
        rows = conn.execute(
            message_select + f" WHERE {where} ORDER BY m.id {order} LIMIT 50",
            params,
        ).fetchall()
        unread = [r["id"] for r in rows if r["sender_id"] != uid]
        if unread:
            stamp = now_iso()
            conn.executemany(
                "INSERT OR IGNORE INTO message_reads(message_id,user_id,read_at) VALUES(?,?,?)",
                [(mid, uid, stamp) for mid in unread],
            )
    if after is None:
        rows = list(reversed(rows))
    return jsonify([rowdict(x) for x in rows])


@app.get("/api/messages/status")
@login_required
def message_status():
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        unread = conn.execute(
            """SELECT COUNT(*) FROM messages m WHERE m.family_id=? AND m.sender_id<>?
               AND NOT EXISTS (SELECT 1 FROM message_reads mr WHERE mr.message_id=m.id AND mr.user_id=?)""",
            (fid, uid, uid),
        ).fetchone()[0]
        typing = conn.execute(
            """SELECT u.name FROM typing_status t JOIN users u ON u.id=t.user_id
               WHERE t.family_id=? AND t.user_id<>? AND t.expires_at>? LIMIT 1""",
            (fid, uid, int(time.time())),
        ).fetchone()
        reads = conn.execute(
            """SELECT m.id,mr.read_at FROM messages m JOIN message_reads mr ON mr.message_id=m.id
               WHERE m.family_id=? AND m.sender_id=? AND mr.user_id<>? ORDER BY m.id DESC LIMIT 100""",
            (fid, uid, uid),
        ).fetchall()
    return jsonify({"unread": unread, "typing_name": typing["name"] if typing else None,
                    "reads": {str(row["id"]): row["read_at"] for row in reads}})


@app.post("/api/messages/typing")
@login_required
@require_csrf
def set_typing():
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("typing"), bool):
        return jsonify({"error": "Invalid typing status."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        if data["typing"]:
            conn.execute(
                """INSERT INTO typing_status(family_id,user_id,expires_at) VALUES(?,?,?)
                   ON CONFLICT(family_id,user_id) DO UPDATE SET expires_at=excluded.expires_at""",
                (fid, uid, int(time.time()) + 6),
            )
        else:
            conn.execute("DELETE FROM typing_status WHERE family_id=? AND user_id=?", (fid, uid))
    return jsonify({"ok": True})


@app.post("/api/messages")
@login_required
@require_csrf
def send_message():
    data = request.get_json(silent=True) or {}
    body = data.get("body", "").strip()
    if not body or len(body) > 12000:
        return jsonify({"error": "Message is too long."}), 400
    fid = require_family()
    uid = session["user_id"]
    created = now_iso()
    with db() as conn:
        # Serialize the chain head read with writes from the other parent.
        conn.execute("BEGIN IMMEDIATE")
        prev = conn.execute(
            "SELECT record_hash FROM messages WHERE family_id=? ORDER BY id DESC LIMIT 1", (fid,)
        ).fetchone()
        prev_hash = prev["record_hash"] if prev else "GENESIS"
        raw = str(fid) + "|" + str(uid) + "|" + created + "|" + body + "|" + prev_hash
        record_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        cur = conn.execute(
            "INSERT INTO messages(family_id,sender_id,body,prev_hash,record_hash,created_at) VALUES(?,?,?,?,?,?)",
            (fid, uid, body, prev_hash, record_hash, created),
        )
        audit_event(conn, fid, uid, "sent", "message", cur.lastrowid, "Sent message", {"hash": record_hash})
        sender = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
        notify_family(conn, fid, uid, "message", "New message from " + sender["name"], body,
                      "message", cur.lastrowid, str(cur.lastrowid))
    return jsonify({"ok": True, "id": cur.lastrowid, "hash": record_hash}), 201


@app.get("/api/messages/verify")
@login_required
def verify_messages():
    fid = require_family()
    with db() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE family_id=? ORDER BY id", (fid,)).fetchall()
    prev = "GENESIS"
    for row in rows:
        raw = str(fid) + "|" + str(row["sender_id"]) + "|" + row["created_at"] + "|" + row["body"] + "|" + prev
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if row["prev_hash"] != prev or row["record_hash"] != expected:
            return jsonify({"verified": False, "broken_at": row["id"]})
        prev = row["record_hash"]
    return jsonify({"verified": True, "count": len(rows), "head_hash": prev})


def rule_warnings(conn, fid, category, start_at):
    warnings = []
    rules = conn.execute("SELECT * FROM rules WHERE family_id=?", (fid,)).fetchall()
    if category == "holiday":
        for rule in rules:
            if rule["rule_type"] == "holiday_notice_days":
                try:
                    days = int(rule["value_text"])
                    start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    notice = (start - datetime.now(timezone.utc)).days
                    if notice < days:
                        warnings.append("Holiday notice is " + str(notice) + " days. Your saved rule requires " + str(days) + " days.")
                except Exception:
                    pass
    return warnings


@app.get("/api/events")
@login_required
def events():
    fid = require_family()
    range_start = parse_datetime(request.args.get("start"))
    range_end = parse_datetime(request.args.get("end"))
    if not range_start:
        range_start = datetime.now().replace(tzinfo=None) - timedelta(days=365)
    if not range_end:
        range_end = datetime.now().replace(tzinfo=None) + timedelta(days=730)
    with db() as conn:
        rows = conn.execute(
            """SELECT e.*,u.name creator_name FROM events e JOIN users u ON u.id=e.creator_id
               WHERE e.family_id=? AND e.cancelled_at IS NULL ORDER BY e.start_at""",
            (fid,),
        ).fetchall()
    occurrences = []
    for row in rows:
        occurrences.extend(expand_event(row, range_start, range_end))
    occurrences.sort(key=lambda item: item["start_at"])
    return jsonify(occurrences[:1000])


def validated_event(data):
    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "general")).strip()
    start_at = str(data.get("start_at", "")).strip()
    end_at = str(data.get("end_at") or "").strip() or None
    recurrence = str(data.get("recurrence", "none")).strip()
    recurrence_until = str(data.get("recurrence_until") or "").strip() or None
    if not title or not start_at:
        raise ValueError("Title and start date are required.")
    if recurrence not in {"none", "daily", "weekly", "monthly"}:
        raise ValueError("Choose a valid repeat option.")
    start = parse_datetime(start_at)
    if end_at and parse_datetime(end_at) <= start:
        raise ValueError("The end time must be after the start time.")
    if recurrence_until and parse_datetime(recurrence_until) < start.replace(hour=0, minute=0, second=0):
        raise ValueError("The repeat end date must be after the first event.")
    try:
        reminder = int(data.get("reminder_minutes") or 0)
        offset = int(data.get("timezone_offset") or 0)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid reminder time.")
    if not 0 <= reminder <= 10080:
        raise ValueError("Reminder must be between 0 minutes and 7 days.")
    if not -840 <= offset <= 840:
        offset = 0
    notes = str(data.get("notes", "")).strip()
    return {
        "title": title if title.startswith("pt1:") else title[:200], "category": category[:40], "start_at": start_at,
        "end_at": end_at, "notes": notes if notes.startswith("pt1:") else notes[:5000],
        "reminder_minutes": reminder, "recurrence": recurrence,
        "recurrence_until": recurrence_until, "timezone_offset": offset,
    }


@app.post("/api/events")
@login_required
@require_csrf
def create_event():
    data = request.get_json(silent=True) or {}
    try:
        item = validated_event(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        warnings = rule_warnings(conn, fid, item["category"], item["start_at"])
        cur = conn.execute(
            """INSERT INTO events(family_id,creator_id,title,category,start_at,end_at,notes,
                   reminder_minutes,recurrence,recurrence_until,timezone_offset,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, uid, item["title"], item["category"], item["start_at"], item["end_at"],
             item["notes"], item["reminder_minutes"], item["recurrence"],
             item["recurrence_until"], item["timezone_offset"], stamp, stamp),
        )
        audit_event(conn, fid, uid, "created", "event", cur.lastrowid,
                    "Calendar event added", {"warnings": warnings, **item})
        notify_family(conn, fid, uid, "event_created", "New calendar event", item["title"],
                      "event", cur.lastrowid, item["start_at"])
    return jsonify({"ok": True, "id": cur.lastrowid, "warnings": warnings}), 201


@app.put("/api/events/<int:item_id>")
@login_required
@require_csrf
def update_event(item_id):
    data = request.get_json(silent=True) or {}
    try:
        updated = validated_event(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        previous = conn.execute(
            "SELECT * FROM events WHERE id=? AND family_id=? AND cancelled_at IS NULL", (item_id, fid)
        ).fetchone()
        if not previous:
            return jsonify({"error": "Event not found."}), 404
        warnings = rule_warnings(conn, fid, updated["category"], updated["start_at"])
        conn.execute(
            """UPDATE events SET title=?,category=?,start_at=?,end_at=?,notes=?,reminder_minutes=?,
                   recurrence=?,recurrence_until=?,timezone_offset=?,updated_at=? WHERE id=? AND family_id=?""",
            (updated["title"], updated["category"], updated["start_at"], updated["end_at"],
             updated["notes"], updated["reminder_minutes"], updated["recurrence"],
             updated["recurrence_until"], updated["timezone_offset"], now_iso(), item_id, fid),
        )
        audit_event(conn, fid, uid, "updated", "event", item_id,
                    "Calendar event updated",
                    {"before": rowdict(previous), "after": updated, "warnings": warnings})
        notify_family(conn, fid, uid, "event_updated", "Calendar event changed", updated["title"],
                      "event", item_id, updated["start_at"])
    return jsonify({"ok": True, "warnings": warnings})


@app.delete("/api/events/<int:item_id>")
@login_required
@require_csrf
def cancel_event(item_id):
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        item = conn.execute(
            "SELECT * FROM events WHERE id=? AND family_id=? AND cancelled_at IS NULL", (item_id, fid)
        ).fetchone()
        if not item:
            return jsonify({"error": "Event not found."}), 404
        conn.execute("UPDATE events SET cancelled_at=?,updated_at=? WHERE id=?", (stamp, stamp, item_id))
        audit_event(conn, fid, uid, "cancelled", "event", item_id,
                    "Calendar event cancelled", {"event": rowdict(item)})
        notify_family(conn, fid, uid, "event_cancelled", "Calendar event cancelled", item["title"],
                      "activity", None, item["start_at"])
    return jsonify({"ok": True})


@app.get("/api/handovers")
@login_required
def list_handovers():
    fid = require_family()
    with db() as conn:
        rows = conn.execute(
            "SELECT h.*,u.name creator_name FROM handovers h JOIN users u ON u.id=h.creator_id WHERE h.family_id=? ORDER BY h.scheduled_at DESC",
            (fid,),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


@app.post("/api/handovers")
@login_required
@require_csrf
def create_handover():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    scheduled = data.get("scheduled_at", "").strip()
    if not title or not scheduled:
        return jsonify({"error": "Handover title and time are required."}), 400
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO handovers(family_id,creator_id,title,scheduled_at,location,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
            (fid, uid, title, scheduled, data.get("location", "").strip(), stamp, stamp),
        )
        audit_event(conn, fid, uid, "requested", "handover", cur.lastrowid, "Handover requested")
        notify_family(conn, fid, uid, "handover_requested", "New handover request", title,
                      "handover", cur.lastrowid, scheduled)
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.post("/api/handovers/<int:item_id>/respond")
@login_required
@require_csrf
def respond_handover(item_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"accepted", "declined", "countered"}:
        return jsonify({"error": "Invalid response."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        item = conn.execute("SELECT * FROM handovers WHERE id=? AND family_id=?", (item_id, fid)).fetchone()
        if not item:
            return jsonify({"error": "Handover not found."}), 404
        note = data.get("response_note", "").strip()
        conn.execute(
            "UPDATE handovers SET status=?,response_note=?,updated_at=? WHERE id=?",
            (status, note, now_iso(), item_id),
        )
        audit_event(conn, fid, uid, status, "handover", item_id, "Handover " + status, {"note": note})
        notify_family(conn, fid, uid, "handover_response", "Handover " + status, item["title"],
                      "handover", item_id, item["scheduled_at"])
    return jsonify({"ok": True})


@app.post("/api/handovers/<int:item_id>/complete")
@login_required
@require_csrf
def complete_handover(item_id):
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        item = conn.execute("SELECT * FROM handovers WHERE id=? AND family_id=?", (item_id, fid)).fetchone()
        if not item:
            return jsonify({"error": "Handover not found."}), 404
        conn.execute("UPDATE handovers SET status='completed',completed_at=?,updated_at=? WHERE id=?", (stamp, stamp, item_id))
        audit_event(conn, fid, uid, "completed", "handover", item_id, "Handover completed", {"completed_at": stamp})
        notify_family(conn, fid, uid, "handover_completed", "Handover completed", item["title"],
                      "handover", item_id, item["scheduled_at"])
    return jsonify({"ok": True, "completed_at": stamp})


@app.get("/api/decisions")
@login_required
def list_decisions():
    fid = require_family()
    with db() as conn:
        rows = conn.execute(
            "SELECT d.*,u.name creator_name FROM decisions d JOIN users u ON u.id=d.creator_id WHERE d.family_id=? ORDER BY d.id DESC",
            (fid,),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


@app.post("/api/decisions")
@login_required
@require_csrf
def create_decision():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Decision title is required."}), 400
    fid = require_family()
    uid = session["user_id"]
    stamp = now_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO decisions(family_id,creator_id,title,details,deadline,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
            (fid, uid, title, data.get("details", "").strip(), data.get("deadline") or None, stamp, stamp),
        )
        audit_event(conn, fid, uid, "requested", "decision", cur.lastrowid, "Decision requested")
        notify_family(conn, fid, uid, "decision_requested", "New decision request", title,
                      "decision", cur.lastrowid, data.get("deadline") or "")
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.post("/api/decisions/<int:item_id>/respond")
@login_required
@require_csrf
def respond_decision(item_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"accepted", "declined", "countered"}:
        return jsonify({"error": "Invalid response."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        item = conn.execute("SELECT * FROM decisions WHERE id=? AND family_id=?", (item_id, fid)).fetchone()
        if not item:
            return jsonify({"error": "Decision not found."}), 404
        note = data.get("response_note", "").strip()
        conn.execute("UPDATE decisions SET status=?,response_note=?,updated_at=? WHERE id=?", (status, note, now_iso(), item_id))
        audit_event(conn, fid, uid, status, "decision", item_id, "Decision " + status, {"note": note})
        notify_family(conn, fid, uid, "decision_response", "Decision " + status, item["title"],
                      "decision", item_id, item["deadline"] or "")
    return jsonify({"ok": True})


@app.get("/api/expenses")
@login_required
def list_expenses():
    fid = require_family()
    with db() as conn:
        rows = conn.execute(
            "SELECT e.*,u.name creator_name FROM expenses e JOIN users u ON u.id=e.creator_id WHERE e.family_id=? ORDER BY e.id DESC",
            (fid,),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.post("/api/expenses")
@login_required
@require_csrf
def create_expense():
    fid = require_family()
    uid = session["user_id"]
    title = request.form.get("title", "").strip()
    try:
        amount_pence = round(float(request.form.get("amount", "0")) * 100)
        split_percent = int(request.form.get("split_percent", "50"))
    except ValueError:
        return jsonify({"error": "Invalid amount or split."}), 400
    if not title or amount_pence <= 0 or not 0 <= split_percent <= 100:
        return jsonify({"error": "Enter a valid expense."}), 400
    receipt_path = None
    file = request.files.get("receipt")
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({"error": "Receipt must be PNG, JPG, WEBP or PDF."}), 400
        safe = secure_filename(file.filename)
        receipt_path = secrets.token_hex(8) + "-" + safe
        file.save(str(Path(app.config["UPLOAD_DIR"]) / receipt_path))
    stamp = now_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO expenses(family_id,creator_id,title,amount_pence,split_percent,due_date,status,receipt_path,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?,?)",
            (fid, uid, title, amount_pence, split_percent, request.form.get("due_date") or None, receipt_path, stamp, stamp),
        )
        audit_event(conn, fid, uid, "requested", "expense", cur.lastrowid, "Expense requested", {"amount_pence": amount_pence, "split_percent": split_percent})
        notify_family(conn, fid, uid, "expense_requested", "New expense request",
                      title, "expense", cur.lastrowid,
                      request.form.get("due_date") or "")
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.post("/api/expenses/<int:item_id>/respond")
@login_required
@require_csrf
def respond_expense(item_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"approved", "declined", "paid"}:
        return jsonify({"error": "Invalid expense status."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        item = conn.execute("SELECT * FROM expenses WHERE id=? AND family_id=?", (item_id, fid)).fetchone()
        if not item:
            return jsonify({"error": "Expense not found."}), 404
        conn.execute("UPDATE expenses SET status=?,updated_at=? WHERE id=?", (status, now_iso(), item_id))
        audit_event(conn, fid, uid, status, "expense", item_id, "Expense " + status)
        notify_family(conn, fid, uid, "expense_response", "Expense " + status, item["title"],
                      "expense", item_id, item["due_date"] or "")
    return jsonify({"ok": True})


@app.get("/api/receipts/<path:filename>")
@login_required
def receipt(filename):
    fid = require_family()
    with db() as conn:
        item = conn.execute("SELECT 1 FROM expenses WHERE family_id=? AND receipt_path=?", (fid, filename)).fetchone()
    if not item:
        return jsonify({"error": "Receipt not found."}), 404
    return send_from_directory(app.config["UPLOAD_DIR"], filename)


@app.post("/api/expenses/<int:item_id>/receipt/encrypt")
@login_required
@require_csrf
def encrypt_legacy_receipt(item_id):
    fid = require_family()
    upload = request.files.get("receipt")
    if not upload or not upload.filename or not upload.filename.endswith(".ptenc"):
        return jsonify({"error": "An encrypted receipt is required."}), 400
    with db() as conn:
        item = conn.execute("SELECT receipt_path FROM expenses WHERE id=? AND family_id=?", (item_id, fid)).fetchone()
        if not item or not item["receipt_path"]:
            return jsonify({"error": "Receipt not found."}), 404
        if item["receipt_path"].endswith(".ptenc"):
            return jsonify({"ok": True, "receipt_path": item["receipt_path"]})
        new_path = secrets.token_hex(16) + ".ptenc"
        destination = Path(app.config["UPLOAD_DIR"]) / new_path
        upload.save(str(destination))
        old_path = Path(app.config["UPLOAD_DIR"]) / item["receipt_path"]
        conn.execute("UPDATE expenses SET receipt_path=?,updated_at=? WHERE id=? AND family_id=?",
                     (new_path, now_iso(), item_id, fid))
    try:
        old_path.unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify({"ok": True, "receipt_path": new_path})


@app.get("/api/rules")
@login_required
def list_rules():
    fid = require_family()
    with db() as conn:
        rows = conn.execute(
            "SELECT r.*,u.name creator_name FROM rules r JOIN users u ON u.id=r.creator_id WHERE r.family_id=? ORDER BY r.id DESC",
            (fid,),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


@app.post("/api/rules")
@login_required
@require_csrf
def create_rule():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    rule_type = data.get("rule_type", "custom").strip()
    value_text = str(data.get("value_text", "")).strip()
    if not title or not value_text:
        return jsonify({"error": "Rule title and value are required."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO rules(family_id,creator_id,title,rule_type,value_text,created_at) VALUES(?,?,?,?,?,?)",
            (fid, uid, title, rule_type, value_text, now_iso()),
        )
        audit_event(conn, fid, uid, "created", "rule", cur.lastrowid, "Agreement rule added", {"type": rule_type})
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.get("/api/timeline")
@login_required
def timeline():
    fid = require_family()
    limit = min(int(request.args.get("limit", "300")), 1000)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT a.*,u.name actor_name,m.body detail
            FROM audit a
            LEFT JOIN users u ON u.id=a.user_id
            LEFT JOIN messages m ON a.entity_type='message' AND m.id=a.entity_id AND m.family_id=a.family_id
            WHERE a.family_id=?
            ORDER BY a.id DESC LIMIT ?
            """,
            (fid, limit),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


def search_variants(query):
    variants = {query}
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
        try:
            variants.add(datetime.strptime(query, fmt).strftime("%Y-%m-%d"))
        except ValueError:
            pass
    for fmt in ("%d/%m", "%d %b", "%d %B", "%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(query, fmt)
            variants.add(f"-{parsed.month:02d}-{parsed.day:02d}")
        except ValueError:
            pass
    for fmt in ("%B %Y", "%b %Y", "%m/%Y"):
        try:
            variants.add(datetime.strptime(query, fmt).strftime("%Y-%m"))
        except ValueError:
            pass
    for month in range(1, 13):
        name = datetime(2000, month, 1)
        if query.casefold() in {name.strftime("%B").casefold(), name.strftime("%b").casefold()}:
            variants.add(f"-{month:02d}-")
    if query.startswith("£"):
        variants.add(query[1:])
    return ["%" + v.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%" for v in variants]


@app.get("/api/search")
@login_required
def search_all():
    fid = require_family()
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    if len(q) > 100:
        return jsonify({"error": "Search is limited to 100 characters."}), 400
    patterns = search_variants(q)
    results = []
    with db() as conn:
        if family_uses_vault(conn, fid):
            return jsonify({"error": "Encrypted records are searched privately on your device."}), 410
        queries = [
            ("message", "m", "FROM messages m JOIN users u ON u.id=m.sender_id",
             "m.id,m.body title,m.created_at,('From '||u.name||' · '||m.created_at) detail",
             ["m.body", "m.created_at", "m.record_hash", "u.name", "u.email", "(SELECT GROUP_CONCAT(read_at,' ') FROM message_reads WHERE message_id=m.id)"]),
            ("event", "e", "FROM (SELECT * FROM events WHERE cancelled_at IS NULL) e JOIN users u ON u.id=e.creator_id",
             "e.id,e.title,e.created_at,(e.category||' · '||e.start_at||' · '||COALESCE(e.notes,'')) detail,e.start_at target_at",
             ["e.title", "e.category", "e.start_at", "e.end_at", "e.notes", "e.created_at", "u.name", "u.email"]),
            ("handover", "h", "FROM handovers h JOIN users u ON u.id=h.creator_id",
             "h.id,h.title,h.created_at,(h.status||' · '||h.scheduled_at||' · '||COALESCE(h.location,'')||' · '||COALESCE(h.response_note,'')) detail",
             ["h.title", "h.scheduled_at", "h.location", "h.status", "h.response_note", "h.completed_at", "h.created_at", "u.name", "u.email"]),
            ("decision", "d", "FROM decisions d JOIN users u ON u.id=d.creator_id",
             "d.id,d.title,d.created_at,(d.status||' · '||COALESCE(d.details,'')||' · '||COALESCE(d.deadline,'')||' · '||COALESCE(d.response_note,'')) detail",
             ["d.title", "d.details", "d.deadline", "d.status", "d.response_note", "d.created_at", "u.name", "u.email"]),
            ("expense", "e", "FROM expenses e JOIN users u ON u.id=e.creator_id",
             "e.id,e.title,e.created_at,(printf('£%.2f',e.amount_pence/100.0)||' · '||e.status||' · '||COALESCE(e.due_date,'')||' · '||COALESCE(e.receipt_path,'')) detail",
             ["e.title", "printf('%.2f',e.amount_pence/100.0)", "e.split_percent", "e.due_date", "e.status", "e.receipt_path", "e.created_at", "u.name", "u.email"]),
            ("rule", "r", "FROM rules r JOIN users u ON u.id=r.creator_id",
             "r.id,r.title,r.created_at,(r.rule_type||' · '||r.value_text) detail",
             ["r.title", "r.rule_type", "r.value_text", "r.created_at", "u.name", "u.email"]),
            ("child", "c", "FROM children c",
             "c.id,c.name title,c.created_at,COALESCE(c.birthday,'Child profile') detail",
             ["c.name", "c.birthday", "c.created_at"]),
            ("activity", "a", "FROM audit a LEFT JOIN users u ON u.id=a.user_id",
             "a.id,a.summary title,a.created_at,(a.entity_type||' · '||a.event_type||' · '||COALESCE(u.name,'System')) detail",
             ["a.summary", "a.entity_type", "a.event_type", "a.metadata_json", "a.created_at", "u.name", "u.email"]),
        ]
        for kind, alias, source, selection, fields in queries:
            conditions = ["COALESCE(CAST(" + field + " AS TEXT),'') LIKE ? ESCAPE '!'" for field in fields for _ in patterns]
            sql = "SELECT " + selection + " " + source + " WHERE " + alias + ".family_id=? AND (" + " OR ".join(conditions) + ") ORDER BY " + alias + ".id DESC LIMIT 100"
            params = [fid] + patterns * len(fields)
            for row in conn.execute(sql, params):
                item = rowdict(row)
                item["type"] = kind
                results.append(item)
    results.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return jsonify(results[:100])


@app.get("/api/evidence.pdf")
@login_required
def evidence_pdf():
    fid = require_family()
    start = request.args.get("start")
    end = request.args.get("end")
    with db() as conn:
        if family_uses_vault(conn, fid):
            return jsonify({"error": "Encrypted messages are exported privately on your device."}), 410
        family = conn.execute("SELECT * FROM families WHERE id=?", (fid,)).fetchone()
        members = conn.execute("SELECT u.name,u.email FROM family_members fm JOIN users u ON u.id=fm.user_id WHERE fm.family_id=?", (fid,)).fetchall()
        children = conn.execute("SELECT name,birthday FROM children WHERE family_id=? ORDER BY name", (fid,)).fetchall()
        message_sql = "SELECT m.*,u.name sender_name FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.family_id=?"
        message_params = [fid]
        if start:
            message_sql += " AND m.created_at>=?"
            message_params.append(start)
        if end:
            message_sql += " AND m.created_at<=?"
            message_params.append(end + "T23:59:59")
        messages = conn.execute(message_sql + " ORDER BY m.id", message_params).fetchall()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=10))
    story = [
        Paragraph("Parenting Together messages", styles["Title"]),
        Paragraph("Generated " + now_iso(), styles["SmallMuted"]),
        Spacer(1, 6*mm),
        Paragraph("Family", styles["Heading2"]),
        Paragraph(html.escape(family["name"]), styles["BodyText"]),
        Paragraph("Parents: " + ", ".join([html.escape(m["name"] + " <" + m["email"] + ">") for m in members]), styles["BodyText"]),
        Paragraph("Children: " + (html.escape(", ".join([c["name"] for c in children])) or "None recorded"), styles["BodyText"]),
        Spacer(1, 5*mm),
        Paragraph("Record integrity", styles["Heading2"]),
        Paragraph("Sent messages cannot be edited or deleted through the app. A SHA-256 hash chain helps detect changes to saved messages. This export does not mean automatic court admissibility.", styles["BodyText"]),
        Spacer(1, 5*mm),
        Paragraph("Messages", styles["Heading2"]),
    ]
    for m in messages:
        story.append(Paragraph(html.escape(m["sender_name"] + " · " + m["created_at"][:19].replace("T", " ")), styles["SmallMuted"]))
        story.append(Paragraph(html.escape(m["body"]), styles["BodyText"]))
        story.append(Paragraph("Hash: " + m["record_hash"], styles["SmallMuted"]))
        story.append(Spacer(1, 4*mm))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name="parenting-together-messages.pdf")


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Upload is too large."}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
