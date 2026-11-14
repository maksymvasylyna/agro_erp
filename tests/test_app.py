import importlib
import os
import tempfile
import unittest

temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp.close()
os.environ["SQLITE_URL"] = "sqlite:///" + temp.name
os.environ["ADMIN_PASSWORD"] = "test-pass-very-secret"
os.environ["COOKIE_SECURE"] = "0"
module = importlib.import_module("app")
app, db = module.app, module.db

class EventAssistantTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def login(self):
        res = self.client.post("/login", data={"password": "test-pass-very-secret"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as s:
            return s["_csrf"]

    def test_protected_dashboard(self):
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_dashboard_and_export(self):
        token = self.login()
        self.assertIn("Панель організатора", self.client.get("/").get_data(as_text=True))
        export = self.client.get("/events/1/export.xlsx")
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export.content_type)

    def test_confirmation_updates_report(self):
        self.login()
        with app.app_context():
            inv = module.Invitation.query.filter_by(event_id=1, status="pending").first()
            token = inv.token
            invite_id = inv.id
        res = self.client.post("/rsvp/" + token, data={"decision":"accepted"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with app.app_context():
            self.assertEqual(db.session.get(module.Invitation, invite_id).status, "accepted")

    def test_send_not_actual_email(self):
        csrf = self.login()
        with app.app_context():
            c = module.Contact.query.first()
            event = module.Event(title="Тест", starts_at="2026-12-30T10:00", location="Онлайн")
            db.session.add(event)
            db.session.flush()
            inv = module.Invitation(event_id=event.id, contact_id=c.id)
            db.session.add(inv)
            db.session.commit()
            event_id = event.id
        response = self.client.post("/events/%d/send"%event_id, data={"_csrf":csrf}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            self.assertIsNotNone(module.Invitation.query.filter_by(event_id=event_id).first().sent_at)

if __name__ == "__main__":
    unittest.main()
