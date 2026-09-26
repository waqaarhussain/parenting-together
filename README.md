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
- SQLite persistence
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

## Resetting all app data

Run:

    reset-parenting-together

Type `RESET` when prompted. This permanently deletes all accounts, families,
children, messages, calendar events, handovers, decisions, expenses, uploaded
receipts, rules and evidence records. The app restarts ready for the first new
account.

## Locations

- App: /opt/parenting-together
- Database: /var/lib/parenting-together/parenting.db
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
