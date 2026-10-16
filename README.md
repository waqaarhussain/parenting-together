# Parenting Together

A mobile-first co-parenting PWA focused on calm communication, verifiable records and simple family logistics.

## What is in v1

- Username or email registration and login
- End-to-end encrypted family content using AES-256-GCM in the browser
- A 16-group recovery phrase that never leaves the user's device
- Device-local protected key storage with recovery on a replacement device
- Single-use typed family invite codes that keep the key hidden from the VPS
- Multiple child profiles
- Saved messages with a SHA-256 hash chain to detect changes
- Delivered/read timestamps
- Shared calendar with rule warnings
- Structured handover requests and completion records
- Structured decisions with accept/decline/counter history
- Shared expenses and receipt uploads
- Agreement rules
- Local decrypted search across messages, dates, names, events, handovers, decisions, expenses and rules
- Chronological evidence timeline
- Local message printing and PDF saving without sending plaintext back to the server
- Light, dark and system themes
- Installable PWA
- PostgreSQL production persistence with SQLite development support
- Server-sent live updates shared across workers via PostgreSQL LISTEN/NOTIFY
- Caddy automatic HTTPS + Gunicorn production service
- update-live helper
- Confirmed full-data reset helper

## Fresh Ubuntu VPS install

Run:

    curl -fsSL https://raw.githubusercontent.com/waqaarhussain/parenting-together/main/install.sh | sudo bash

Then open:

    https://v2202603253680444276.megasrv.de

The installer creates a random server secret. There are no default accounts or hard-coded passwords.

## Updating later

Run:

    update-live

### First PostgreSQL upgrade

The existing `update-live` command is sufficient. The updated systemd service
prepares PostgreSQL before starting the app, including when the update was
launched using the previous version of the helper.

The app stops briefly while the first upgrade installs PostgreSQL and copies the
SQLite database. A consistent SQLite backup is saved with root-only permissions.
The import preserves record IDs, timestamps, password hashes, vault envelopes,
ciphertext and message hashes. Every table is checked by row count and SHA-256
digest before a single transaction commits. The source SQLite file and uploads
are kept in place. `DATABASE_URL` is written only after a successful copy.
Repeated updates do not reimport the old database.

The managed database uses a local Unix socket and the existing `www-data` service
identity, without a database password in GitHub. No public database port is needed.
The server secret and browser vault keys are not changed by migration.

Before later starts, the service saves a PostgreSQL dump once per UTC day. These
local backups are retained; they must also be copied off the VPS for protection
against a complete disk loss or VPS reset. Monitor their disk usage and set a
retention policy appropriate to the service before a public launch.

If migration fails, the environment remains on SQLite and the original source is
preserved. The service stays stopped so no writes can diverge between databases.
Inspect `journalctl -u parenting-together -n 100 --no-pager` and fix the reported
cause before restarting. Do not manually remove `DATABASE_URL` after users have
started writing to PostgreSQL: SQLite is then an out-of-date rollback snapshot.

### Live update behaviour

Each active app opens one authenticated `/api/live` SSE connection. One shared
PostgreSQL LISTEN connection per worker distributes committed family changes;
there is no per-client database connection held for an idle stream. Bounded
queues merge bursts. Notifications contain table/routing metadata, never message
text, vault passwords or keys. The browser fetches authorized, encrypted records
through the existing API after an update. Reconnects and foregrounding trigger a
fresh fetch, so no event replay log is required.

Streams close in the background and refresh after reopening. A 30-second polling
fallback is used while a stream is unavailable. Heartbeats keep streams alive,
and active users' event reminders are checked by the server every 15 seconds.
This is foreground app synchronization, not a new lock-screen push service.

The initial service uses two threaded workers with 128 threads each, capped at
96 streams per worker and three per account per worker, reserving capacity for
normal API requests. Each worker has a bounded database pool of eight connections.
These are operating limits, not a tested user-capacity guarantee; load-test before
a larger public launch. SQLite development mode uses the slower polling fallback.

## Resetting all app data

Run:

    reset-parenting-together

Type `RESET` when prompted. This permanently deletes all accounts, families,
children, messages, calendar events, handovers, decisions, expenses, uploaded
receipts, rules and evidence records. The app restarts ready for the first new
account. The reset clears the PostgreSQL tables and local uploads. It retains
existing backup files, which must be removed separately if a complete backup purge
is intended.

## Locations

- App: /opt/parenting-together
- Production database: local PostgreSQL database `parenting_together`
- Previous SQLite database: /var/lib/parenting-together/parenting.db
- Migration and local database backups: /var/backups/parenting-together
- Uploads: /var/lib/parenting-together/uploads
- Environment: /etc/parenting-together.env
- Service: parenting-together.service
- HTTPS certificates: /var/lib/caddy

Caddy renews certificates automatically. The app data reset does not remove its
certificate storage. A complete Ubuntu reinstall removes `/var/lib/caddy`, so
back that directory up first if you intend to wipe the whole VPS repeatedly.

## Encryption model

Shared text and receipt files are encrypted on the user's device before upload.
The VPS stores ciphertext, operational metadata and a recovery-wrapped family
key. The recovery phrase is not uploaded. Search, receipt decryption and message
export happen in the browser after the vault is unlocked.

Calendar times, record types, account names, usernames, optional email addresses,
status values and record timestamps remain visible to the server so reminders,
ordering and account delivery work. Losing every device and the recovery phrase
means the encrypted family data cannot be recovered.

This browser version materially limits routine database access, but the final
App Store build should also pin the signed client and receive an independent
security review before making an absolute claim that the service operator can
never access plaintext.

## Important evidence wording

Parenting Together creates tamper-evident, timestamped records and exportable evidence packs. It does not claim that any record is automatically admissible in court. Admissibility is determined by the relevant court or tribunal.

## Development

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    export SECRET_KEY=dev-only-change-me
    flask --app app run --debug


### Integration checks

Run `python -m unittest discover -s tests -v` for SQLite flows. To also run the
same flows, verified-copy migration, concurrent messages and live family-isolation
checks on a disposable PostgreSQL database, set `PG_TEST_URL` before running the
suite. **That database is truncated by the tests; never use production credentials.**
GitHub Actions runs these checks using PostgreSQL 16 and separately exercises the
real systemd startup migration, repeated startup and full-data reset on a disposable
Ubuntu runner.
