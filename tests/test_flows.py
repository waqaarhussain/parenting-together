import io
import os
import tempfile
import unittest
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
        self.assertTrue(self.first.get("/api/timeline").json)
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


if __name__ == "__main__":
    unittest.main()
