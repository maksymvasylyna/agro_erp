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

    def test_pdf_contact_extraction(self):
        fields = module.pdf_contact_fields(
            "МАКСИМ ВАСИЛИНА\nГоловний агроном | Головний агроном холдингу\n"
            "Кропивницький • +38 068 988 47 81 • contact@example.com"
        )
        self.assertEqual(fields["name"], "Максим Василина")
        self.assertEqual(fields["email"], "contact@example.com")
        self.assertEqual(fields["company"], "")

    def test_semicolon_csv_import(self):
        csrf = self.login()
        import io
        payload = "ПІБ;Компанія;Email\nТест Тестовий;Приклад;demo-contact99@example.com\n"
        response = self.client.post(
            "/contacts/import", data={"_csrf": csrf, "file": (io.BytesIO(payload.encode("utf-8")), "contacts.csv")},
            content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            self.assertIsNotNone(module.Contact.query.filter_by(email="demo-contact99@example.com").first())

    def test_send_confirmation_get_does_not_change_state(self):
        csrf = self.login()
        with app.app_context():
            c = module.Contact.query.first()
            event = module.Event(title="Перевірка розсилки", starts_at="2026-12-22T12:00", location="Онлайн")
            db.session.add(event)
            db.session.flush()
            inv = module.Invitation(event_id=event.id, contact_id=c.id)
            db.session.add(inv)
            db.session.commit()
            event_id, inv_id = event.id, inv.id
        confirmation = self.client.get("/events/%d/send" % event_id)
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Підтвердити імітацію", confirmation.get_data(as_text=True))
        with app.app_context():
            self.assertIsNone(db.session.get(module.Invitation, inv_id).sent_at)
        result = self.client.post("/events/%d/send" % event_id,
                                  data={"_csrf": csrf}, follow_redirects=True)
        self.assertEqual(result.status_code, 200)
        with app.app_context():
            self.assertIsNotNone(db.session.get(module.Invitation, inv_id).sent_at)
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id, kind="invitation").count(), 1)
        # Sending twice must be idempotent.
        second = self.client.post("/events/%d/send" % event_id,
                                  data={"_csrf": csrf}, follow_redirects=True)
        self.assertEqual(second.status_code, 200)
        with app.app_context():
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id, kind="invitation").count(), 1)

    def test_send_demo_event_already_sent_message(self):
        self.login()
        response = self.client.get("/events/1/send")
        self.assertEqual(response.status_code, 200)
        self.assertIn("вже позначені", response.get_data(as_text=True))

    def test_create_personal_test_event_from_environment(self):
        from unittest.mock import patch
        csrf = self.login()
        recipient = "personal-test@example.com"
        with patch.dict(os.environ, {"TEST_RECIPIENT_EMAIL": recipient}):
            response = self.client.post("/test/create", data={"_csrf": csrf}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
        with app.app_context():
            c = module.Contact.query.filter_by(email=recipient).one()
            e = module.Event.query.filter_by(title="Тестова розсилка Event Assistant").order_by(module.Event.id.desc()).first()
            self.assertIsNotNone(e)
            self.assertEqual(len(e.invitations), 1)
            self.assertEqual(e.invitations[0].contact_id, c.id)
            self.assertIsNone(e.invitations[0].sent_at)

    def test_real_send_is_not_available_without_configuration(self):
        from unittest.mock import patch
        self.login()
        with patch.dict(os.environ, {"RESEND_API_KEY": "", "TEST_RECIPIENT_EMAIL": ""}, clear=False):
            r = self.client.get("/events/1/test-email")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Пошту ще не підключено", r.get_data(as_text=True))

    def test_real_send_one_recipient_with_mocked_provider(self):
        from unittest.mock import patch
        import resend
        csrf = self.login()
        with app.app_context():
            contact = module.Contact.query.first()
            event = module.Event(title="Реальний тест листа", starts_at="2026-12-22T10:00", location="Онлайн")
            db.session.add(event)
            db.session.flush()
            inv = module.Invitation(event_id=event.id, contact_id=contact.id)
            db.session.add(inv)
            db.session.commit()
            event_id = event.id
            recipient_email = contact.email
        with patch.dict(os.environ, {"TEST_RECIPIENT_EMAIL": recipient_email, "RESEND_API_KEY": "dummy-test-token"}):
            with patch.object(resend.Emails, "send", return_value={"id":"test-message-id"}) as sender:
                response = self.client.get("/events/%d/test-email" % event_id)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(sender.call_count, 0)
                response = self.client.post("/events/%d/test-email" % event_id, data={"_csrf":csrf}, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(sender.call_count, 1)
                payload = sender.call_args.args[0]
                self.assertEqual(payload["to"], [recipient_email])
                self.assertIn("Підтвердити", payload["html"])
                self.client.post("/events/%d/test-email" % event_id, data={"_csrf":csrf})
                self.assertEqual(sender.call_count, 1)
        with app.app_context():
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id, kind="real_test").count(), 1)

    def test_provider_error_does_not_mark_invitation_sent(self):
        from unittest.mock import patch
        import resend
        csrf = self.login()
        with app.app_context():
            contact = module.Contact.query.first()
            event = module.Event(title="Помилка пошти", starts_at="2026-12-23T11:00", location="Онлайн")
            db.session.add(event)
            db.session.flush()
            inv = module.Invitation(event_id=event.id, contact_id=contact.id)
            db.session.add(inv)
            db.session.commit()
            event_id, invitation_id = event.id, inv.id
            recipient_email = contact.email
        with patch.dict(os.environ, {"TEST_RECIPIENT_EMAIL": recipient_email, "RESEND_API_KEY": "dummy-test-token"}):
            with patch.object(resend.Emails, "send", side_effect=ValueError("denied")):
                r = self.client.post("/events/%d/test-email" % event_id, data={"_csrf":csrf}, follow_redirects=True)
                self.assertEqual(r.status_code, 200)
                self.assertIn("Resend відхилив", r.get_data(as_text=True))
        with app.app_context():
            self.assertIsNone(db.session.get(module.Invitation, invitation_id).sent_at)
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id, kind="real_test").count(), 0)

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
