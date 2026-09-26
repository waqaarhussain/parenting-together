import io
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_import_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_import_dir.name) / "import.db")
os.environ["UPLOAD_DIR"] = str(Path(_import_dir.name) / "uploads")
os.environ["SECRET_KEY"] = "test-only-secret"

from app import app, db, init_db


class TwoParentFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.config.update(TESTING=True, DATABASE_PATH=str(Path(self.tmp.name) / "test.db"),
                          UPLOAD_DIR=str(Path(self.tmp.name) / "uploads"))
        Path(app.config["UPLOAD_DIR"]).mkdir()
        init_db()
        self.first = app.test_client()
        self.second = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def register(self, client, name, email):
        response = client.post("/api/auth/register", json={"name": name, "email": email, "password": "sample-password-123"})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.json

    def post(self, client, csrf, path, json=None, data=None):
        return client.post(path, json=json, data=data, headers={"X-CSRF-Token": csrf})

    def test_join_and_shared_features(self):
        a = self.register(self.first, "Parent One", "one@example.test")
        b = self.register(self.second, "Parent Two", "two@example.test")
        old_family = b["family"]["id"]
        response = self.post(self.second, b["csrf"], "/api/family/join", {"invite_code": a["family"]["invite_code"].lower()})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.json["family"]["id"], a["family"]["id"])
        self.assertEqual(len(response.json["members"]), 2)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit WHERE family_id=?", (old_family,)).fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM family_members WHERE family_id=?", (old_family,)).fetchone()[0], 0)

        sent = self.post(self.first, a["csrf"], "/api/messages", {"body": "School pickup Tuesday"})
        self.assertEqual(sent.status_code, 201, sent.get_data(as_text=True))
        self.assertEqual(self.second.get("/api/messages").json[0]["body"], "School pickup Tuesday")
        self.assertTrue(self.first.get("/api/messages").json[0]["read_at"])
        self.assertTrue(self.first.get("/api/messages/verify").json["verified"])

        child = self.post(self.first, a["csrf"], "/api/children", {"name": "Alex"})
        self.assertEqual(child.status_code, 201, child.get_data(as_text=True))
        self.assertEqual(self.second.get("/api/me").json["children"][0]["name"], "Alex")
        event = self.post(self.first, a["csrf"], "/api/events", {"title": "School pickup", "category": "school", "start_at": "2026-10-05T15:30"})
        self.assertEqual(event.status_code, 201, event.get_data(as_text=True))
        self.assertEqual(self.second.get("/api/events").json[0]["title"], "School pickup")

        handover = self.post(self.first, a["csrf"], "/api/handovers", {"title": "Friday handover", "scheduled_at": "2026-10-09T17:00"})
        self.assertEqual(handover.status_code, 201, handover.get_data(as_text=True))
        self.assertEqual(self.post(self.second, b["csrf"], f"/api/handovers/{handover.json['id']}/respond", {"status": "accepted"}).status_code, 200)
        self.assertEqual(self.post(self.first, a["csrf"], f"/api/handovers/{handover.json['id']}/complete").status_code, 200)
        self.assertEqual(self.second.get("/api/handovers").json[0]["status"], "completed")

        decision = self.post(self.first, a["csrf"], "/api/decisions", {"title": "School trip", "details": "Wednesday"})
        self.assertEqual(decision.status_code, 201, decision.get_data(as_text=True))
        self.assertEqual(self.post(self.second, b["csrf"], f"/api/decisions/{decision.json['id']}/respond", {"status": "accepted"}).status_code, 200)
        self.assertEqual(self.first.get("/api/decisions").json[0]["status"], "accepted")

        expense = self.post(self.first, a["csrf"], "/api/expenses", data={"title": "School trip fee", "amount": "12.50", "split_percent": "50", "receipt": (io.BytesIO(b"%PDF-1.4\nexample"), "receipt.pdf")})
        self.assertEqual(expense.status_code, 201, expense.get_data(as_text=True))
        self.assertEqual(self.post(self.second, b["csrf"], f"/api/expenses/{expense.json['id']}/respond", {"status": "approved"}).status_code, 200)
        receipt_path = self.second.get("/api/expenses").json[0]["receipt_path"]
        receipt = self.second.get("/api/receipts/" + receipt_path)
        self.assertEqual(receipt.status_code, 200)
        receipt.close()

        rule = self.post(self.first, a["csrf"], "/api/rules", {"title": "Holiday notice", "rule_type": "holiday_notice_days", "value_text": "28"})
        self.assertEqual(rule.status_code, 201, rule.get_data(as_text=True))
        self.assertTrue(self.second.get("/api/search?q=school").json)
        self.assertIn("message", {item["type"] for item in self.second.get("/api/search?q=Parent%20One").json})
        self.assertIn("event", {item["type"] for item in self.second.get("/api/search?q=05%2F10%2F2026").json})
        self.assertIn("event", {item["type"] for item in self.second.get("/api/search?q=October%202026").json})
        self.assertIn("handover", {item["type"] for item in self.second.get("/api/search?q=09%2F10%2F2026").json})
        self.assertIn("expense", {item["type"] for item in self.second.get("/api/search?q=%C2%A312.50").json})
        self.assertIn("expense", {item["type"] for item in self.second.get("/api/search?q=receipt.pdf").json})
        self.assertIn("child", {item["type"] for item in self.second.get("/api/search?q=Alex").json})
        self.assertIn("rule", {item["type"] for item in self.second.get("/api/search?q=holiday_notice_days").json})
        self.assertIn("activity", {item["type"] for item in self.second.get("/api/search?q=calendar%20event").json})
        self.assertIn("decision", {item["type"] for item in self.second.get("/api/search?q=Wednesday").json})
        timeline = self.first.get("/api/timeline").json
        self.assertTrue(timeline)
        message_activity = next(item for item in timeline if item["entity_type"] == "message")
        self.assertEqual(message_activity["detail"], "School pickup Tuesday")
        pdf = self.second.get("/api/evidence.pdf")
        self.assertEqual(pdf.status_code, 200, pdf.get_data(as_text=True)[:300] if pdf.status_code != 200 else "")
        self.assertTrue(pdf.data.startswith(b"%PDF"))

    def test_join_preserves_existing_family_records(self):
        a = self.register(self.first, "Parent One", "one@example.test")
        b = self.register(self.second, "Parent Two", "two@example.test")
        self.assertEqual(self.post(self.second, b["csrf"], "/api/children", {"name": "Alex"}).status_code, 201)
        response = self.post(self.second, b["csrf"], "/api/family/join", {"invite_code": a["family"]["invite_code"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.second.get("/api/me").json["family"]["id"], b["family"]["id"])
        self.assertEqual(self.second.get("/api/me").json["children"][0]["name"], "Alex")

    def test_live_status_and_unlimited_history(self):
        a = self.register(self.first, "Parent One", "one@example.test")
        b = self.register(self.second, "Parent Two", "two@example.test")
        self.assertEqual(self.post(self.second, b["csrf"], "/api/family/join", {"invite_code": a["family"]["invite_code"]}).status_code, 200)
        for number in range(123):
            response = self.post(self.first, a["csrf"], "/api/messages", {"body": f"Message {number}"})
            self.assertEqual(response.status_code, 201)
        self.assertEqual(self.second.get("/api/messages/status").json["unread"], 123)

        latest = self.second.get("/api/messages").json
        self.assertEqual(len(latest), 50)
        self.assertEqual(latest[0]["body"], "Message 73")
        self.assertEqual(latest[-1]["body"], "Message 122")
        self.assertEqual(self.second.get("/api/messages/status").json["unread"], 73)
        self.assertTrue(self.first.get("/api/messages/status").json["reads"])

        middle = self.second.get(f"/api/messages?before={latest[0]['id']}").json
        self.assertEqual(len(middle), 50)
        self.assertEqual(middle[0]["body"], "Message 23")
        earliest = self.second.get(f"/api/messages?before={middle[0]['id']}").json
        self.assertEqual(len(earliest), 23)
        self.assertEqual(earliest[0]["body"], "Message 0")
        self.assertEqual(self.second.get("/api/messages/status").json["unread"], 0)
        self.assertEqual(self.second.get(f"/api/messages?after={latest[-1]['id']}").json, [])
        context = self.second.get(f"/api/messages?around={middle[10]['id']}").json
        self.assertEqual(context["target_id"], middle[10]["id"])
        self.assertTrue(context["has_older"])
        self.assertTrue(context["has_newer"])
        self.assertIn(middle[10]["id"], {message["id"] for message in context["messages"]})

        self.assertEqual(self.post(self.first, a["csrf"], "/api/messages/typing", {"typing": True}).status_code, 200)
        self.assertEqual(self.second.get("/api/messages/status").json["typing_name"], "Parent One")
        with db() as conn:
            conn.execute("UPDATE typing_status SET expires_at=?", (int(time.time()) - 1,))
        self.assertIsNone(self.second.get("/api/messages/status").json["typing_name"])
        self.assertEqual(self.post(self.first, a["csrf"], "/api/messages/typing", {"typing": True}).status_code, 200)
        self.assertEqual(self.post(self.first, a["csrf"], "/api/messages/typing", {"typing": False}).status_code, 200)
        self.assertIsNone(self.second.get("/api/messages/status").json["typing_name"])

    def test_notifications_recurring_events_and_event_changes(self):
        a = self.register(self.first, "Parent One", "one@example.test")
        b = self.register(self.second, "Parent Two", "two@example.test")
        self.assertEqual(self.post(self.second, b["csrf"], "/api/family/join", {"invite_code": a["family"]["invite_code"]}).status_code, 200)

        joined = self.first.get("/api/notifications").json
        self.assertEqual(joined["unread"], 1)
        self.assertEqual(joined["items"][0]["notification_type"], "family_joined")
        self.assertEqual(self.post(self.first, a["csrf"], "/api/notifications/read", {}).status_code, 200)

        self.assertEqual(self.post(self.first, a["csrf"], "/api/messages", {"body": "Bring the school bag"}).status_code, 201)
        message_notice = self.second.get("/api/notifications").json
        self.assertTrue(any(item["notification_type"] == "message" for item in message_notice["items"]))

        starts = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(tzinfo=None, second=0, microsecond=0)
        repeat_until = (starts + timedelta(days=2)).date().isoformat()
        payload = {"title": "Medicine", "category": "appointment", "start_at": starts.isoformat(timespec="minutes"),
                   "end_at": "", "notes": "Bring prescription", "reminder_minutes": 60,
                   "recurrence": "daily", "recurrence_until": repeat_until, "timezone_offset": 0}
        created = self.post(self.first, a["csrf"], "/api/events", payload)
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        event_id = created.json["id"]

        event_rows = self.second.get(
            "/api/events?start=" + starts.date().isoformat() + "&end=" + (starts + timedelta(days=3)).isoformat()
        ).json
        self.assertEqual(len([item for item in event_rows if item["id"] == event_id]), 3)
        self.assertTrue(all(item["is_recurring"] for item in event_rows if item["id"] == event_id))

        creator_notices = self.first.get("/api/notifications").json
        self.assertTrue(any(item["notification_type"] == "event_reminder" for item in creator_notices["items"]))
        other_notices = self.second.get("/api/notifications").json
        self.assertTrue(any(item["notification_type"] == "event_created" for item in other_notices["items"]))

        payload["title"] = "Updated medicine appointment"
        updated = self.first.put(f"/api/events/{event_id}", json=payload, headers={"X-CSRF-Token": a["csrf"]})
        self.assertEqual(updated.status_code, 200, updated.get_data(as_text=True))
        event_search = self.second.get("/api/search?q=Updated%20medicine").json
        match = next(item for item in event_search if item["type"] == "event")
        self.assertEqual(match["id"], event_id)
        self.assertEqual(match["target_at"], payload["start_at"])

        cancelled = self.first.delete(f"/api/events/{event_id}", json={}, headers={"X-CSRF-Token": a["csrf"]})
        self.assertEqual(cancelled.status_code, 200)
        remaining = self.second.get(
            "/api/events?start=" + starts.date().isoformat() + "&end=" + (starts + timedelta(days=3)).isoformat()
        ).json
        self.assertFalse(any(item["id"] == event_id for item in remaining))
        event_activity = [item["event_type"] for item in self.first.get("/api/timeline").json if item["entity_type"] == "event"]
        self.assertIn("updated", event_activity)
        self.assertIn("cancelled", event_activity)


if __name__ == "__main__":
    unittest.main()
