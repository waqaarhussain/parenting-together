import hashlib
import io
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, session
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["DATABASE_PATH"] = os.environ.get("DATABASE_PATH", str(Path(__file__).with_name("parenting.db")))
app.config["UPLOAD_DIR"] = os.environ.get("UPLOAD_DIR", str(Path(__file__).with_name("uploads")))
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}

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
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        start_at TEXT NOT NULL,
        end_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
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


init_db()


def rowdict(row):
    return dict(row) if row else None


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


def audit_event(conn, fid, uid, event_type, entity_type, entity_id, summary, metadata=None):
    conn.execute(
        "INSERT INTO audit(family_id,user_id,event_type,entity_type,entity_id,summary,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (fid, uid, event_type, entity_type, entity_id, summary, json.dumps(metadata or {}), now_iso()),
    )


def unique_invite_code(conn):
    for _ in range(20):
        code = secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM families WHERE invite_code=?", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate invite code")


def me_payload(uid):
    with db() as conn:
        user = conn.execute("SELECT id,name,email,created_at FROM users WHERE id=?", (uid,)).fetchone()
        fid = family_id_for(uid)
        family = None
        members = []
        children = []
        if fid:
            family = conn.execute("SELECT id,name,invite_code,created_at FROM families WHERE id=?", (fid,)).fetchone()
            members = conn.execute(
                "SELECT u.id,u.name,u.email,fm.role,fm.joined_at FROM family_members fm JOIN users u ON u.id=fm.user_id WHERE fm.family_id=? ORDER BY fm.joined_at",
                (fid,),
            ).fetchall()
            children = conn.execute("SELECT * FROM children WHERE family_id=? ORDER BY name", (fid,)).fetchall()
    return {
        "user": rowdict(user),
        "family": rowdict(family),
        "members": [rowdict(x) for x in members],
        "children": [rowdict(x) for x in children],
        "csrf": csrf_token(),
    }


@app.get("/")
def index():
    return render_template("index.html")


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
    password = data.get("password", "")
    if len(name) < 2 or "@" not in email or len(password) < 8:
        return jsonify({"error": "Use a name, valid email and password of at least 8 characters."}), 400
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                (name, email, generate_password_hash(password), now_iso()),
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
            audit_event(conn, fid, uid, "created", "family", fid, "Created family space")
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409
    session.clear()
    session["user_id"] = uid
    csrf_token()
    return jsonify(me_payload(uid)), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 401
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


@app.post("/api/family/join")
@login_required
@require_csrf
def join_family():
    data = request.get_json(silent=True) or {}
    code = data.get("invite_code", "").strip().upper()
    uid = session["user_id"]
    if not code:
        return jsonify({"error": "Enter an invite code."}), 400
    with db() as conn:
        target = conn.execute("SELECT * FROM families WHERE invite_code=?", (code,)).fetchone()
        if not target:
            return jsonify({"error": "Invite code not found."}), 404
        if conn.execute("SELECT 1 FROM family_members WHERE family_id=? AND user_id=?", (target["id"], uid)).fetchone():
            return jsonify(me_payload(uid))
        current = family_id_for(uid)
        if current:
            member_count = conn.execute("SELECT COUNT(*) c FROM family_members WHERE family_id=?", (current,)).fetchone()["c"]
            activity_count = 0
            for table in ("messages", "events", "handovers", "decisions", "expenses"):
                activity_count += conn.execute("SELECT COUNT(*) c FROM " + table + " WHERE family_id=?", (current,)).fetchone()["c"]
            if member_count == 1 and activity_count == 0:
                conn.execute("DELETE FROM family_members WHERE family_id=? AND user_id=?", (current, uid))
                conn.execute("DELETE FROM families WHERE id=?", (current,))
            else:
                return jsonify({"error": "This account is already attached to an active family space."}), 409
        conn.execute(
            "INSERT INTO family_members(family_id,user_id,role,joined_at) VALUES(?,?,?,?)",
            (target["id"], uid, "parent", now_iso()),
        )
        audit_event(conn, target["id"], uid, "joined", "family", target["id"], "Joined family space")
    return jsonify(me_payload(uid))


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
        audit_event(conn, fid, session["user_id"], "created", "child", cur.lastrowid, "Added child profile: " + name)
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.get("/api/messages")
@login_required
def list_messages():
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        rows = conn.execute(
            """
            SELECT m.*,u.name sender_name,
                   (SELECT MIN(read_at) FROM message_reads mr WHERE mr.message_id=m.id AND mr.user_id<>m.sender_id) read_at
            FROM messages m JOIN users u ON u.id=m.sender_id
            WHERE m.family_id=? ORDER BY m.id ASC LIMIT 500
            """,
            (fid,),
        ).fetchall()
        unread = [r["id"] for r in rows if r["sender_id"] != uid]
        if unread:
            stamp = now_iso()
            conn.executemany(
                "INSERT OR IGNORE INTO message_reads(message_id,user_id,read_at) VALUES(?,?,?)",
                [(mid, uid, stamp) for mid in unread],
            )
    return jsonify([rowdict(x) for x in rows])


@app.post("/api/messages")
@login_required
@require_csrf
def send_message():
    data = request.get_json(silent=True) or {}
    body = data.get("body", "").strip()
    if not body or len(body) > 5000:
        return jsonify({"error": "Message must be between 1 and 5,000 characters."}), 400
    fid = require_family()
    uid = session["user_id"]
    created = now_iso()
    with db() as conn:
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
        audit_event(conn, fid, uid, "sent", "message", cur.lastrowid, "Sent immutable message", {"hash": record_hash})
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
    with db() as conn:
        rows = conn.execute(
            "SELECT e.*,u.name creator_name FROM events e JOIN users u ON u.id=e.creator_id WHERE e.family_id=? ORDER BY e.start_at",
            (fid,),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


@app.post("/api/events")
@login_required
@require_csrf
def create_event():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    start_at = data.get("start_at", "").strip()
    category = data.get("category", "general").strip()
    if not title or not start_at:
        return jsonify({"error": "Title and start date are required."}), 400
    fid = require_family()
    uid = session["user_id"]
    with db() as conn:
        warnings = rule_warnings(conn, fid, category, start_at)
        cur = conn.execute(
            "INSERT INTO events(family_id,creator_id,title,category,start_at,end_at,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (fid, uid, title, category, start_at, data.get("end_at") or None, data.get("notes", "").strip(), now_iso()),
        )
        audit_event(conn, fid, uid, "created", "event", cur.lastrowid, "Calendar event: " + title, {"warnings": warnings})
    return jsonify({"ok": True, "id": cur.lastrowid, "warnings": warnings}), 201


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
        audit_event(conn, fid, uid, "requested", "handover", cur.lastrowid, "Handover requested: " + title)
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
        audit_event(conn, fid, uid, status, "handover", item_id, "Handover " + status + ": " + item["title"], {"note": note})
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
        audit_event(conn, fid, uid, "completed", "handover", item_id, "Handover completed: " + item["title"], {"completed_at": stamp})
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
        audit_event(conn, fid, uid, "requested", "decision", cur.lastrowid, "Decision requested: " + title)
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
        audit_event(conn, fid, uid, status, "decision", item_id, "Decision " + status + ": " + item["title"], {"note": note})
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
        audit_event(conn, fid, uid, "requested", "expense", cur.lastrowid, "Expense requested: " + title, {"amount_pence": amount_pence, "split_percent": split_percent})
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
        audit_event(conn, fid, uid, status, "expense", item_id, "Expense " + status + ": " + item["title"])
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
        audit_event(conn, fid, uid, "created", "rule", cur.lastrowid, "Agreement rule added: " + title, {"type": rule_type, "value": value_text})
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.get("/api/timeline")
@login_required
def timeline():
    fid = require_family()
    limit = min(int(request.args.get("limit", "300")), 1000)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT a.*,u.name actor_name
            FROM audit a LEFT JOIN users u ON u.id=a.user_id
            WHERE a.family_id=?
            ORDER BY a.id DESC LIMIT ?
            """,
            (fid, limit),
        ).fetchall()
    return jsonify([rowdict(x) for x in rows])


@app.get("/api/search")
@login_required
def search_all():
    fid = require_family()
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    like = "%" + q + "%"
    results = []
    with db() as conn:
        queries = [
            ("message", "SELECT id,body title,created_at,'' detail FROM messages WHERE family_id=? AND body LIKE ? ORDER BY id DESC LIMIT 25"),
            ("event", "SELECT id,title,created_at,COALESCE(notes,'') detail FROM events WHERE family_id=? AND (title LIKE ? OR notes LIKE ?) ORDER BY id DESC LIMIT 25"),
            ("handover", "SELECT id,title,created_at,COALESCE(location,'') detail FROM handovers WHERE family_id=? AND (title LIKE ? OR location LIKE ?) ORDER BY id DESC LIMIT 25"),
            ("decision", "SELECT id,title,created_at,COALESCE(details,'') detail FROM decisions WHERE family_id=? AND (title LIKE ? OR details LIKE ?) ORDER BY id DESC LIMIT 25"),
            ("expense", "SELECT id,title,created_at,status detail FROM expenses WHERE family_id=? AND title LIKE ? ORDER BY id DESC LIMIT 25"),
            ("rule", "SELECT id,title,created_at,value_text detail FROM rules WHERE family_id=? AND (title LIKE ? OR value_text LIKE ?) ORDER BY id DESC LIMIT 25"),
        ]
        for kind, sql in queries:
            count_q = sql.count("?") - 1
            params = [fid] + [like] * count_q
            for row in conn.execute(sql, params).fetchall():
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
        family = conn.execute("SELECT * FROM families WHERE id=?", (fid,)).fetchone()
        members = conn.execute("SELECT u.name,u.email FROM family_members fm JOIN users u ON u.id=fm.user_id WHERE fm.family_id=?", (fid,)).fetchall()
        children = conn.execute("SELECT name,birthday FROM children WHERE family_id=? ORDER BY name", (fid,)).fetchall()
        sql = "SELECT a.*,u.name actor_name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.family_id=?"
        params = [fid]
        if start:
            sql += " AND a.created_at>=?"
            params.append(start)
        if end:
            sql += " AND a.created_at<=?"
            params.append(end + "T23:59:59")
        sql += " ORDER BY a.id ASC"
        audits = conn.execute(sql, params).fetchall()
        messages = conn.execute(
            "SELECT m.*,u.name sender_name FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.family_id=? ORDER BY m.id",
            (fid,),
        ).fetchall()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=10))
    story = [
        Paragraph("Parenting Together evidence pack", styles["Title"]),
        Paragraph("Generated " + now_iso(), styles["SmallMuted"]),
        Spacer(1, 6*mm),
        Paragraph("Family", styles["Heading2"]),
        Paragraph(family["name"], styles["BodyText"]),
        Paragraph("Parents: " + ", ".join([m["name"] + " <" + m["email"] + ">" for m in members]), styles["BodyText"]),
        Paragraph("Children: " + (", ".join([c["name"] for c in children]) or "None recorded"), styles["BodyText"]),
        Spacer(1, 5*mm),
        Paragraph("Record integrity", styles["Heading2"]),
        Paragraph("Messages are stored as immutable database records and linked by a SHA-256 hash chain. This export is a tamper-evident record, not a claim of automatic court admissibility.", styles["BodyText"]),
        Spacer(1, 5*mm),
        Paragraph("Chronological activity", styles["Heading2"]),
    ]
    data = [["Time", "Actor", "Type", "Record"]]
    for a in audits:
        data.append([a["created_at"][:19].replace("T", " "), a["actor_name"] or "System", a["entity_type"], a["summary"]])
    table = Table(data, colWidths=[38*mm, 32*mm, 24*mm, 82*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.extend([table, PageBreak(), Paragraph("Message record", styles["Heading2"])])
    for m in messages:
        story.append(Paragraph(m["sender_name"] + " · " + m["created_at"][:19].replace("T", " "), styles["SmallMuted"]))
        story.append(Paragraph(m["body"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"]))
        story.append(Paragraph("Hash: " + m["record_hash"], styles["SmallMuted"]))
        story.append(Spacer(1, 4*mm))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name="parenting-together-evidence.pdf")


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Upload is too large."}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
