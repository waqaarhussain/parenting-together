# Parenting Together

A mobile-first co-parenting PWA focused on calm communication, verifiable records and simple family logistics.

## What is in v1

- Secure account registration and login
- Family invite codes and solo mode
- Multiple child profiles
- Saved messages with a SHA-256 hash chain to detect changes
- Delivered/read timestamps
- Shared calendar with rule warnings
- Structured handover requests and completion records
- Structured decisions with accept/decline/counter history
- Shared expenses and receipt uploads
- Agreement rules
- Global search across messages, events, handovers, decisions, expenses and rules
- Chronological evidence timeline
- PDF evidence export
- Light, dark and system themes
- Installable PWA
- SQLite persistence
- Nginx + Gunicorn production service
- update-live helper
- Confirmed full-data reset helper

## Fresh Ubuntu VPS install

Run:

    curl -fsSL https://raw.githubusercontent.com/waqaarhussain/parenting-together/main/install.sh | sudo bash

Then open:

    http://YOUR_VPS_IP

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

## Important evidence wording

Parenting Together creates tamper-evident, timestamped records and exportable evidence packs. It does not claim that any record is automatically admissible in court. Admissibility is determined by the relevant court or tribunal.

## Development

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    export SECRET_KEY=dev-only-change-me
    flask --app app run --debug
