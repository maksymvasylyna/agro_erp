import importlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp.close()
os.environ["SQLITE_URL"] = "sqlite:///" + temp.name
os.environ["ADMIN_PASSWORD"] = "test-pass-very-secret"
os.environ["COOKIE_SECURE"] = "0"
module = importlib.import_module("app")
app, db = module.app, module.db


class EventAssistantTests(unittest.TestCase):
    def setUp(self):
        with app.app_context():
            db.drop_all()
            db.create_all()
        self.client = app.test_client()

    def login(self):
        res = self.client.post("/login", data={"password": "test-pass-very-secret"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as session:
            return session["_csrf"]

    def add_contact(self, email="person@example.com"):
        with app.app_context():
            item = module.Contact(name="Ірина Коваль", company="АгроКомпанія", email=email)
            db.session.add(item)
            db.session.commit()
            return item.id

    def add_event(self, emails):
        with app.app_context():
            event = module.Event(title="Навчання для партнерів", starts_at="2026-12-22T12:00", location="Онлайн",
                                 description="Огляд технологій")
            db.session.add(event)
            db.session.flush()
            event_id = event.id
            for email in emails:
                contact = module.Contact.query.filter_by(email=email).one()
                db.session.add(module.Invitation(event_id=event_id, contact_id=contact.id))
            db.session.commit()
            return event_id

    def test_dashboard_protected_and_no_seeded_data(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.login()
        r = self.client.get("/")
        self.assertIn("Панель організатора", r.get_data(as_text=True))
        self.assertNotIn("Створити особистий тест", r.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(module.Contact.query.count(), 0)
            self.assertEqual(module.Event.query.count(), 0)

    def test_new_event_requires_second_explicit_confirmation_before_email(self):
        import resend
        csrf = self.login()
        contact_id = self.add_contact()
        with patch.object(resend.Emails, "send") as sender:
            r = self.client.post("/events/new", data={"_csrf":csrf,
                  "title":"Навчання з агрономії", "starts_at":"2026-12-20T10:00",
                  "location":"Кропивницький", "contact_ids":str(contact_id)}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn("Підтвердження розсилки", r.get_data(as_text=True))
            self.assertEqual(sender.call_count, 0)
        with app.app_context():
            inv = module.Invitation.query.first()
            self.assertIsNone(inv.sent_at)

    def test_confirmed_email_and_private_rsvp(self):
        import resend
        csrf = self.login()
        recipient = "person@example.com"
        self.add_contact(recipient)
        event_id = self.add_event([recipient])
        with patch.dict(os.environ, {"RESEND_API_KEY":"re_dummy", "TEST_RECIPIENT_EMAIL":recipient,
                                       "EMAIL_FROM":"Event Assistant <onboarding@resend.dev>"}):
            with patch.object(resend.Emails, "send", return_value={"id":"mail-id"}) as sender:
                get = self.client.get("/events/%d/send" % event_id)
                self.assertEqual(get.status_code, 200)
                self.assertEqual(sender.call_count, 0)
                post = self.client.post("/events/%d/send" % event_id,
                                        data={"_csrf":csrf}, follow_redirects=True)
                self.assertEqual(post.status_code, 200)
                self.assertEqual(sender.call_count, 1)
                payload = sender.call_args.args[0]
                self.assertEqual(payload["to"], [recipient])
                self.assertIn("Беру участь", payload["html"])
                self.assertIn("Не зможу", payload["html"])
                self.client.post("/events/%d/send" % event_id, data={"_csrf":csrf})
                self.assertEqual(sender.call_count, 1)
        with app.app_context():
            inv = module.Invitation.query.filter_by(event_id=event_id).one()
            self.assertIsNotNone(inv.sent_at)
            token, inv_id = inv.token, inv.id
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id,kind="invitation").count(), 1)
        preview = self.client.get("/rsvp/" + token + "?choice=accepted")
        self.assertIn("Підтвердити вибір", preview.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(db.session.get(module.Invitation, inv_id).status, "pending")
        r = self.client.post("/rsvp/" + token, data={"decision":"accepted"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with app.app_context():
            self.assertEqual(db.session.get(module.Invitation, inv_id).status, "accepted")
        report = self.client.get("/events/%d" % event_id).get_data(as_text=True)
        self.assertIn("Підтвердив", report)

    def test_restricted_sender_blocks_other_recipients(self):
        import resend
        csrf = self.login()
        self.add_contact("other@example.com")
        event_id = self.add_event(["other@example.com"])
        with patch.dict(os.environ, {"RESEND_API_KEY":"re_dummy",
                                       "TEST_RECIPIENT_EMAIL":"owner@example.com",
                                       "EMAIL_FROM":"onboarding@resend.dev"}):
            with patch.object(resend.Emails,"send") as send:
                page = self.client.get("/events/%d/send" % event_id).get_data(as_text=True)
                self.assertIn("власну адресу", page)
                self.client.post("/events/%d/send" % event_id,
                                 data={"_csrf":csrf}, follow_redirects=True)
                self.assertEqual(send.call_count, 0)
        with app.app_context():
            self.assertIsNone(module.Invitation.query.filter_by(event_id=event_id).one().sent_at)

    def test_provider_failure_is_redacted_and_retryable(self):
        import resend
        csrf = self.login()
        recipient="person@example.com"
        self.add_contact(recipient)
        event_id=self.add_event([recipient])
        key="re_keySecret987654"
        reason="API key is invalid: " + key + " for " + recipient
        with patch.dict(os.environ, {"RESEND_API_KEY":key, "TEST_RECIPIENT_EMAIL":recipient,
                                       "EMAIL_FROM":"onboarding@resend.dev"}):
            with patch.object(resend.Emails,"send",side_effect=ValueError(reason)) as sender:
                r=self.client.post("/events/%d/send" % event_id,
                                  data={"_csrf":csrf}, follow_redirects=True)
                self.assertEqual(sender.call_count,1)
        result=r.get_data(as_text=True)
        self.assertIn("API key is invalid",result)
        self.assertNotIn(key,result)
        self.assertNotIn(recipient,result.split("Помилка надсилання:")[-1].split("Невідправлені")[0])
        with app.app_context():
            self.assertIsNone(module.Invitation.query.filter_by(event_id=event_id).one().sent_at)
            self.assertEqual(module.MessageLog.query.filter_by(event_id=event_id,kind="failed").count(),1)

    def test_verified_sender_can_send_multiple_addresses(self):
        import resend
        csrf=self.login()
        recipients=["a@example.com","b@example.com"]
        for r in recipients:
            self.add_contact(r)
        event_id=self.add_event(recipients)
        with patch.dict(os.environ, {"RESEND_API_KEY":"re_dummy", "EMAIL_FROM":"Events <events@verified.example>"}):
            with patch.object(resend.Emails,"send",return_value={"id":"test-id"}) as sender:
                r=self.client.post("/events/%d/send" % event_id,
                                   data={"_csrf":csrf},follow_redirects=True)
                self.assertEqual(r.status_code,200)
                self.assertEqual(sender.call_count,2)

    def test_old_test_routes_and_simulation_ui_absent(self):
        self.login()
        self.assertEqual(self.client.post("/test/create").status_code,404)
        self.assertEqual(self.client.get("/events/1/test-email").status_code,404)
        self.assertEqual(self.client.post("/events/1/remind").status_code,404)
        self.assertNotIn("Імітувати розсилку",self.client.get("/").get_data(as_text=True))

    def test_pdf_contact_extraction(self):
        fields=module.pdf_contact_fields("МАКСИМ ВАСИЛИНА\nКропивницький +380689884781 contact@example.com")
        self.assertEqual(fields["name"],"Максим Василина")
        self.assertEqual(fields["email"],"contact@example.com")

    def test_semicolon_csv_import(self):
        csrf=self.login()
        payload="ПІБ;Компанія;Email\nТест Тестовий;Приклад;demo-contact99@example.com\n"
        r=self.client.post("/contacts/import",
            data={"_csrf":csrf,"file":(io.BytesIO(payload.encode("utf-8")),"contacts.csv")},
            content_type="multipart/form-data",follow_redirects=True)
        self.assertEqual(r.status_code,200)
        with app.app_context():
            self.assertIsNotNone(module.Contact.query.filter_by(email="demo-contact99@example.com").first())

    def test_export(self):
        self.login()
        self.add_contact()
        event_id=self.add_event(["person@example.com"])
        r=self.client.get("/events/%d/export.xlsx" % event_id)
        self.assertEqual(r.status_code,200)
        self.assertIn("spreadsheetml",r.content_type)


if __name__ == "__main__":
    unittest.main()
