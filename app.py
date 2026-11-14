import csv
import hmac
import io
import html
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps

from flask import Flask, abort, flash, make_response, redirect, render_template_string, request, send_file, session, url_for
from flask_sqlalchemy import SQLAlchemy
from markupsafe import Markup
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader
from sqlalchemy import UniqueConstraint

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = (os.environ.get("DATABASE_URL") or os.environ.get("SQLITE_URL") or "sqlite:////tmp/event_assistant_demo.sqlite3").replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE") == "1"
db = SQLAlchemy(app)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    company = db.Column(db.String(160), nullable=False, default="")
    position = db.Column(db.String(120), default="")
    region = db.Column(db.String(120), default="")
    email = db.Column(db.String(254), nullable=False, unique=True)
    phone = db.Column(db.String(60), default="")

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False)
    starts_at = db.Column(db.String(24), nullable=False)
    location = db.Column(db.String(250), default="")
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    invitations = db.relationship("Invitation", backref="event", cascade="all,delete-orphan")

class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey("contact.id"), nullable=False)
    token = db.Column(db.String(80), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    status = db.Column(db.String(20), nullable=False, default="pending")
    sent_at = db.Column(db.DateTime)
    responded_at = db.Column(db.DateTime)
    contact = db.relationship("Contact")
    __table_args__ = (UniqueConstraint("event_id", "contact_id", name="uq_event_contact"),)

class MessageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, nullable=False)
    contact_id = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def status_label(inv):
    if not inv.sent_at:
        return "Не надіслано"
    return {"pending": "Очікуємо", "accepted": "Підтвердив", "declined": "Відмовився"}.get(inv.status, inv.status)

def event_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y · %H:%M")
    except (ValueError, TypeError):
        return value

app.jinja_env.filters["event_date"] = event_date

LAYOUT = """
<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — Event Assistant</title>
<style>
:root{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#192841;background:#f5f7fb}
*{box-sizing:border-box}body{margin:0}a{color:inherit;text-decoration:none}
.layout{display:flex;min-height:100vh}.sidebar{width:245px;background:#112849;color:#e8eef8;padding:30px 20px;flex-shrink:0}
.brand{font-size:20px;font-weight:800;letter-spacing:-.5px;color:#fff}.brand span{color:#f8bc4a}
.subtitle{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#91a6c4;margin:10px 0 36px}
.nav a{display:block;padding:13px 14px;margin:7px 0;border-radius:10px;font-weight:600;font-size:14px}
.nav a:hover{background:#244266}.logout{margin-top:30px}
.main{width:100%;min-width:0;padding:35px max(30px,5vw)}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.eyebrow{color:#7c8aa0;font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin:0 0 7px}
h1{font-size:30px;letter-spacing:-1px;margin:0}h2{font-size:19px;margin:0 0 20px}h3{font-size:16px;margin:0 0 14px}
.card{background:#fff;border:1px solid #e5eaf1;border-radius:17px;padding:24px;box-shadow:0 4px 19px rgba(15,39,74,.035)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.two{display:grid;grid-template-columns:1.3fr 1fr;gap:20px}.spacer{height:20px}
.metric{font-size:38px;font-weight:800;letter-spacing:-1px}.muted{font-size:13px;color:#7c8aa0}.tag{border-radius:99px;padding:5px 10px;font-size:12px;font-weight:700;display:inline-block;background:#eef2fa;color:#526786}
.tag.accepted{color:#168657;background:#e7f8ee}.tag.declined{color:#b83e48;background:#ffebeb}.tag.pending{color:#95620b;background:#fff4da}
.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;border-bottom:1px solid #eaf0f5;padding:14px 10px}th{font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:#8996aa}
.btn{background:#1b4f96;color:#fff;border:0;display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:9px;padding:11px 15px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap}
.btn:hover{background:#143e78}.btn.secondary{background:#edf2f9;color:#244b7e}.btn.gold{background:#e8ae42;color:#192841}
.btn.small{padding:8px 10px;font-size:12px}.actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
input,select,textarea{border:1px solid #d7dfeb;border-radius:9px;padding:11px 12px;font:inherit;font-size:13px;background:#fff;width:100%;color:#192841}
input[type=checkbox]{width:auto;accent-color:#1b4f96}textarea{min-height:100px}label{display:block;font-size:12px;color:#53647d;font-weight:700;margin:12px 0 6px}
.fields{display:grid;grid-template-columns:repeat(2,1fr);gap:0 18px}.note{background:#fff8e9;border:1px solid #fae5b7;padding:13px 16px;border-radius:11px;font-size:13px;color:#7f5818}
.flash{background:#e8f7ef;color:#206845;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px}
.row{display:flex;justify-content:space-between;gap:10px;align-items:center}.section{margin-top:24px}.list{max-height:330px;overflow:auto;border:1px solid #e7ecf3;border-radius:10px;padding:6px 14px}
.person{border-bottom:1px solid #eff2f8;padding:11px 2px;display:flex;align-items:center;gap:10px;font-size:13px}
.person small{display:block;color:#7e8ba0;margin-top:3px}.person:last-child{border:0}
.progress{height:11px;background:#e8edf3;border-radius:20px;overflow:hidden;display:flex;margin:15px 0}
.progress span{height:100%}.checklist{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
@media(max-width:900px){.sidebar{width:190px}.grid{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}.main{padding:24px}}
@media(max-width:610px){.layout{display:block}.sidebar{width:100%;padding:17px}.subtitle{display:none}.nav{display:flex;gap:4px;flex-wrap:wrap}.nav a{margin:4px 0;padding:9px}.logout{margin:0}.main{padding:20px}.grid{gap:9px}.card{padding:17px}h1{font-size:24px}.fields{grid-template-columns:1fr}}
</style></head><body>
<div class="layout"><aside class="sidebar">
<div class="brand">EVENT <span>ASSISTANT</span></div><div class="subtitle">Навчання • конференції • події</div>
<div class="nav">{% if authed %}
<a href="{{ url_for('dashboard') }}">◫ &nbsp;Огляд</a>
<a href="{{ url_for('event_new') }}">▦ &nbsp;Новий захід</a>
<a href="{{ url_for('contacts') }}">♧ &nbsp;Контакти</a>
<form action="{{ url_for('logout') }}" method="post" class="logout"><input type="hidden" name="_csrf" value="{{ csrf }}"><button class="btn secondary small">Вийти</button></form>
{% endif %}</div></aside>
<main class="main"><div class="top"><div><p class="eyebrow">Демонстраційна версія · без реальної розсилки</p><h1>{{ title }}</h1></div><span class="tag">MVP 1.0</span></div>
{% for msg in flashes %}<div class="flash">{{ msg }}</div>{% endfor %}
{{ body }}
</main></div></body></html>
"""

def page(title, body, **context):
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["_csrf"] = token
    content = render_template_string(body, csrf=token, **context)
    return render_template_string(LAYOUT, title=title, body=Markup(content), csrf=token,
                                  authed=session.get("authenticated"), flashes=[x[1] for x in __import__("flask").get_flashed_messages(with_categories=True)])

@app.before_request
def authenticate():
    if request.endpoint in {"login", "rsvp", "health", "static"}:
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    if request.method == "POST" and not hmac.compare_digest(str(request.form.get("_csrf", "")), str(session.get("_csrf", ""))):
        abort(400, description="Некоректний захисний токен")
    return None

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

LOGIN = """
<div class="card" style="max-width:440px"><p class="muted">Вхід до кабінету організатора</p>
<form method="post"><label>Пароль демоверсії</label><input type="password" name="password" required autofocus>
<div class="spacer"></div><button class="btn">Увійти →</button></form></div>
"""
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected = os.environ.get("ADMIN_PASSWORD", "")
        if expected and hmac.compare_digest(str(request.form.get("password", "")), expected):
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("dashboard"))
        flash("Неправильний пароль або пароль не налаштовано", "error")
    return page("Вхід", LOGIN)

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/health")
def health():
    return {"ok": True, "name": "event-assistant", "mode": "simulation"}

DASH = """
<div class="note">Це демонстраційний стенд. Звичайна імітація та нагадування не надсилають листів. Реальний тестовий email доступний окремо після підключення Resend — тільки на одну дозволену адресу.</div>
<div class="spacer"></div>
<div class="card"><h3>Перевірка справжнього листа через Resend</h3>
<p class="muted">Створимо окреме навчання тільки для однієї тестової адреси з налаштувань Render. Після створення ти зможеш відкрити захід і підтвердити відправлення одного справжнього листа.</p>
<form method="post" action="{{ url_for('create_personal_test') }}"><input type="hidden" name="_csrf" value="{{ csrf }}">
<button type="submit" class="btn gold">+ Створити особистий тест →</button>
</form></div>
<div class="spacer"></div>
<div class="grid">
<div class="card"><div class="muted">Контакти</div><div class="metric">{{ n_contacts }}</div></div>
<div class="card"><div class="muted">Заходи</div><div class="metric">{{ n_events }}</div></div>
<div class="card"><div class="muted">Підтвердили</div><div class="metric" style="color:#168657">{{ accepted }}</div></div>
<div class="card"><div class="muted">Очікуємо відповіді</div><div class="metric" style="color:#ad7c20">{{ pending }}</div></div>
</div>
<div class="section"><div class="row"><h2>Заходи</h2><a class="btn" href="{{ url_for('event_new') }}">+ Створити захід</a></div>
<div class="card tablewrap"><table><thead><tr><th>Захід</th><th>Дата / час</th><th>Локація</th><th>Запрошено</th><th></th></tr></thead><tbody>
{% for event in events %}<tr><td><b>{{ event.title }}</b></td><td>{{ event.starts_at|event_date }}</td><td>{{ event.location }}</td><td>{{ event.invitations|length }}</td><td><a class="btn secondary small" href="{{ url_for('event_detail', event_id=event.id) }}">Відкрити →</a></td></tr>
{% else %}<tr><td colspan="5">Заходів поки немає</td></tr>{% endfor %}
</tbody></table></div></div>
"""
@app.get("/")
def dashboard():
    events = Event.query.order_by(Event.starts_at.desc()).all()
    invs = Invitation.query.all()
    return page("Панель організатора", DASH, events=events,
                n_contacts=Contact.query.count(), n_events=len(events),
                accepted=sum(i.sent_at is not None and i.status == "accepted" for i in invs),
                pending=sum(i.sent_at is not None and i.status == "pending" for i in invs))

def pdf_contact_fields(text):
    """Conservatively extract a single contact from text-based CV PDFs."""
    lines = [re.sub(r"\s+", " ", line).strip(" •\t") for line in text.splitlines()]
    lines = [line for line in lines if line]
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text, flags=re.UNICODE)
    phone_match = re.search(r"(?:\+?\s?38[\s\-()]*)?0\d{2}[\s\-()]*(?:\d[\s\-()]*){7}", text)
    name = ""
    for line in lines[:15]:
        if (2 <= len(line.split()) <= 4
            and re.fullmatch(r"[А-ЯІЇЄҐ'’\-\s]+", line)
            and len(line) <= 100):
            name = line.title()
            break
    position = ""
    for line in lines[:12]:
        if "|" in line and not any("@" in part for part in line.split("|")):
            position = line.split("|")[-1].strip()
            break
    return {
        "name": name,
        "company": "",
        "email": email_match.group(0).lower() if email_match else "",
        "phone": phone_match.group(0).strip() if phone_match else "",
        "position": position[:120],
        "region": ""
    }

PDF_PREVIEW = """
<div class="note">PDF розпізнано як одне резюме. Перевірте кожне поле, особливо компанію й посаду: PDF не завжди містить структуровані дані. Контакт ще не збережений.</div>
<div class="spacer"></div>
<div class="card" style="max-width:730px"><h2>Перевірка контакту з PDF</h2>
<form action="{{ url_for('contact_add') }}" method="post"><input type="hidden" name="_csrf" value="{{ csrf }}">
<div class="fields">
<div><label>ПІБ *</label><input name="name" value="{{ item.name }}" required maxlength="160"></div>
<div><label>Компанія *</label><input name="company" value="{{ item.company }}" placeholder="Вкажіть компанію" required maxlength="160"></div>
<div><label>Email *</label><input name="email" type="email" value="{{ item.email }}" required maxlength="254"></div>
<div><label>Телефон</label><input name="phone" value="{{ item.phone }}" maxlength="60"></div>
<div><label>Посада</label><input name="position" value="{{ item.position }}" maxlength="120"></div>
<div><label>Регіон</label><input name="region" value="{{ item.region }}" maxlength="120"></div>
</div><div class="spacer"></div><div class="actions">
<button class="btn">Підтвердити і зберегти</button><a href="{{ url_for('contacts') }}" class="btn secondary">Скасувати</a>
</div></form></div>
"""

CONTACTS = """
<div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
<div class="card"><h2>Новий контакт</h2>
<form action="{{ url_for('contact_add') }}" method="post"><input type="hidden" name="_csrf" value="{{ csrf }}">
<div class="fields"><div><label>ПІБ *</label><input name="name" required></div><div><label>Компанія *</label><input name="company" required></div>
<div><label>Email *</label><input name="email" type="email" required></div><div><label>Телефон</label><input name="phone"></div>
<div><label>Посада</label><input name="position"></div><div><label>Регіон</label><input name="region"></div></div>
<div class="spacer"></div><button class="btn">Зберегти контакт</button></form></div>
<div class="card"><h2>Імпорт Excel / CSV / PDF</h2><p class="muted">Для Excel/CSV: колонки ПІБ, Компанія, Email, Телефон, Посада, Регіон. Для PDF: текстове резюме одного контакту з перевіркою перед збереженням. До 2 МБ. Дублікати email пропускаємо.</p>
<form action="{{ url_for('contacts_import') }}" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{ csrf }}"><input type="file" name="file" accept=".xlsx,.csv,.pdf" required><div class="spacer"></div><button class="btn secondary">Імпортувати</button></form></div></div>
<div class="section"><div class="row"><h2>База контактів · {{ contacts|length }}</h2><input id="search" style="max-width:270px" placeholder="Пошук..." oninput="filterRows(this.value)"></div>
<div class="card tablewrap"><table id="contacts"><thead><tr><th>Контакт</th><th>Компанія</th><th>Email</th><th>Телефон</th><th>Регіон</th></tr></thead><tbody>
{% for p in contacts %}<tr><td><b>{{ p.name }}</b><div class="muted">{{ p.position }}</div></td><td>{{ p.company }}</td><td>{{ p.email }}</td><td>{{ p.phone }}</td><td>{{ p.region }}</td></tr>{% endfor %}
</tbody></table></div></div>
<script>function filterRows(v){document.querySelectorAll("#contacts tbody tr").forEach(function(tr){tr.style.display=tr.innerText.toLowerCase().includes(v.toLowerCase())?"":"none"})}</script>
"""
@app.get("/contacts")
def contacts():
    return page("Контакти", CONTACTS, contacts=Contact.query.order_by(Contact.company, Contact.name).all())

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
@app.post("/contacts/add")
def contact_add():
    name = request.form.get("name", "").strip()[:160]
    company = request.form.get("company", "").strip()[:160]
    email = request.form.get("email", "").strip().lower()[:254]
    if not name or not company or not EMAIL_RE.fullmatch(email):
        flash("Перевірте ПІБ, компанію та email", "error")
    elif Contact.query.filter_by(email=email).first():
        flash("Контакт із цим email уже існує", "error")
    else:
        db.session.add(Contact(name=name, company=company, email=email,
                               position=request.form.get("position", "").strip()[:120],
                               region=request.form.get("region", "").strip()[:120],
                               phone=request.form.get("phone", "").strip()[:60]))
        db.session.commit()
        flash("Контакт додано", "success")
    return redirect(url_for("contacts"))

@app.post("/contacts/import")
def contacts_import():
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith((".xlsx", ".csv", ".pdf")):
        flash("Виберіть файл .xlsx, .csv або .pdf", "error")
        return redirect(url_for("contacts"))
    try:
        if upload.filename.lower().endswith(".pdf"):
            pdf = PdfReader(io.BytesIO(upload.read()))
            if pdf.is_encrypted:
                raise ValueError("Захищений паролем PDF не підтримується")
            if not pdf.pages or len(pdf.pages) > 20:
                raise ValueError("PDF повинен мати від 1 до 20 сторінок")
            source = "\n".join((page.extract_text() or "") for page in pdf.pages)[:50000]
            if not source.strip():
                raise ValueError("PDF не містить доступного тексту; для сканів потрібне OCR")
            item = pdf_contact_fields(source)
            return page("Перевірка імпорту PDF", PDF_PREVIEW, item=item)
        if upload.filename.lower().endswith(".xlsx"):
            book = load_workbook(io.BytesIO(upload.read()), read_only=True, data_only=True)
            sheet = book.active
            rows = sheet.iter_rows(values_only=True)
        else:
            source = upload.read().decode("utf-8-sig")
            try:
                dialect = csv.Sniffer().sniff(source[:4096], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = csv.reader(io.StringIO(source), dialect=dialect)
        columns = next(rows, None)
        if not columns:
            raise ValueError("Порожній файл")
        alias = {"піб":"name", "ім'я":"name", "ім’я":"name", "name":"name",
                 "компанія":"company", "company":"company", "email":"email", "e-mail":"email",
                 "телефон":"phone", "phone":"phone", "посада":"position", "position":"position",
                 "регіон":"region", "region":"region"}
        keys = [alias.get(str(x or "").strip().lower(), "") for x in columns]
        if not {"name", "company", "email"}.issubset(keys):
            raise ValueError("Потрібні колонки ПІБ, Компанія, Email")
        existing = {x.email for x in Contact.query.all()}
        count = 0
        for row in rows:
            if count >= 1000:
                break
            item = {key: str(value or "").strip() for key, value in zip(keys, row) if key}
            email = item.get("email", "").lower()[:254]
            if (not EMAIL_RE.fullmatch(email) or email in existing or
                not item.get("name") or not item.get("company")):
                continue
            db.session.add(Contact(name=item["name"][:160], company=item["company"][:160],
                                   email=email, position=item.get("position", "")[:120],
                                   region=item.get("region", "")[:120], phone=item.get("phone", "")[:60]))
            existing.add(email)
            count += 1
        db.session.commit()
        flash("Імпортовано нових контактів: " + str(count), "success")
    except Exception as exc:
        db.session.rollback()
        flash("Не вдалось імпортувати файл: " + str(exc)[:160], "error")
    return redirect(url_for("contacts"))

EVENT_NEW = """
<form method="post"><input type="hidden" name="_csrf" value="{{ csrf }}">
<div class="two"><div class="card"><h2>Інформація про захід</h2>
<label>Назва заходу *</label><input name="title" placeholder="Навчання для партнерів" required maxlength="220">
<div class="fields"><div><label>Дата і час *</label><input type="datetime-local" name="starts_at" required></div>
<div><label>Місце проведення</label><input name="location" placeholder="Місто, адреса або онлайн"></div></div>
<label>Опис / програма</label><textarea name="description" placeholder="Коротка програма..."></textarea>
<div class="spacer"></div><button class="btn gold">Створити захід →</button></div>
<div class="card"><div class="row"><h2>Оберіть учасників</h2><span class="muted" id="selected">0 обрано</span></div>
<input id="finder" placeholder="Пошук за ім'ям, компанією, регіоном..." oninput="filterPeople(this.value)">
<div class="checklist"><label><input type="checkbox" id="all" onchange="selectAll(this.checked)"> Обрати всіх видимих</label></div>
<div class="list" id="people">
{% for p in contacts %}<label class="person"><input type="checkbox" name="contact_ids" value="{{ p.id }}" onchange="countSelected()">
<span><b>{{ p.name }}</b><small>{{ p.company }} · {{ p.region }}</small></span></label>{% endfor %}
</div><p class="muted">Запрошення з'являться в звіті після створення заходу. У демо відправка лише моделюється.</p>
</div></div></form>
<script>
function countSelected(){document.getElementById("selected").textContent=document.querySelectorAll("#people input:checked").length+" обрано"}
function filterPeople(v){document.querySelectorAll("#people .person").forEach(function(p){p.style.display=p.innerText.toLowerCase().includes(v.toLowerCase())?"":"none"})}
function selectAll(v){document.querySelectorAll("#people .person").forEach(function(p){if(p.style.display!=="none")p.querySelector("input").checked=v});countSelected()}
</script>
"""
@app.route("/events/new", methods=["GET", "POST"])
def event_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:220]
        starts_at = request.form.get("starts_at", "").strip()
        try:
            datetime.fromisoformat(starts_at)
        except ValueError:
            starts_at = ""
        selected = sorted(set(int(x) for x in request.form.getlist("contact_ids") if x.isdigit()))
        valid = Contact.query.filter(Contact.id.in_(selected)).all() if selected else []
        if not title or not starts_at or not valid:
            flash("Вкажіть назву, дату і виберіть учасників", "error")
        else:
            event = Event(title=title, starts_at=starts_at,
                          location=request.form.get("location", "").strip()[:250],
                          description=request.form.get("description", "").strip()[:4000])
            db.session.add(event)
            db.session.flush()
            for person in valid:
                db.session.add(Invitation(event_id=event.id, contact_id=person.id))
            db.session.commit()
            flash("Захід створено. Запрошення ще не надіслані.", "success")
            return redirect(url_for("event_detail", event_id=event.id))
    return page("Новий захід", EVENT_NEW, contacts=Contact.query.order_by(Contact.company,Contact.name).all())

EVENT_DETAIL = """
<div class="note">Імітація не надсилає листів. Для реальної перевірки пошти оберіть окрему дію «Тестовий email» — вона надсилає максимум один лист на дозволену адресу за захищеним налаштуванням.</div>
<div class="spacer"></div>
<div class="row" style="flex-wrap:wrap"><div><p class="eyebrow">{{ event.starts_at|event_date }} · {{ event.location }}</p><h2 style="margin:4px 0">{{ event.title }}</h2><div class="muted">{{ event.description }}</div></div>
<div class="actions"><a href="{{ url_for('event_export',event_id=event.id) }}" class="btn secondary">↓ Excel</a><a href="{{ url_for('event_csv',event_id=event.id) }}" class="btn secondary">↓ CSV</a></div></div>
<div class="spacer"></div>
<div class="grid">
<div class="card"><div class="muted">Учасників</div><div class="metric">{{ total }}</div></div>
<div class="card"><div class="muted">Підтвердили</div><div class="metric" style="color:#168657">{{ accepted }}</div></div>
<div class="card"><div class="muted">Відмовилися</div><div class="metric" style="color:#b83e48">{{ declined }}</div></div>
<div class="card"><div class="muted">Очікують / не надіслано</div><div class="metric" style="color:#ad7c20">{{ pending + unsent }}</div></div>
</div>
<div class="progress"><span style="width:{{ accepted_pct }}%;background:#35ad7d"></span><span style="width:{{ declined_pct }}%;background:#e66e75"></span></div>
<div class="card section"><h3>Автоматизація — демонстрація</h3><div class="actions">
{% if unsent > 0 %}<a class="btn" href="{{ url_for('event_send',event_id=event.id) }}">✉ Імітувати розсилку ({{ unsent }}) →</a>{% else %}<span class="tag accepted">✓ Усі запрошення вже імітовано</span>{% endif %}
<a class="btn gold" href="{{ url_for('send_test_email',event_id=event.id) }}">✉ Тестовий email →</a>
<form method="post" action="{{ url_for('event_remind',event_id=event.id) }}"><input type="hidden" name="_csrf" value="{{ csrf }}"><input type="hidden" name="audience" value="pending"><button class="btn secondary">Нагадати без відповіді ({{ pending }})</button></form>
<form method="post" action="{{ url_for('event_remind',event_id=event.id) }}"><input type="hidden" name="_csrf" value="{{ csrf }}"><input type="hidden" name="audience" value="accepted"><button class="btn secondary">Нагадати підтвердженим ({{ accepted }})</button></form>
</div>{% if unsent == 0 %}<p class="muted">У цьому заході немає нових запрошень для відправлення. Для повного тесту створіть <a href="{{ url_for('event_new') }}" style="color:#1b4f96;text-decoration:underline">новий захід</a> і виберіть учасників.</p>{% endif %}<p class="muted">Запланована автоматична розсилка буде доступна після підключення постачальника пошти та зовнішнього планувальника.</p></div>
<div class="section card tablewrap"><div class="row"><h2>Звіт по учасниках</h2><input style="max-width:260px" id="finder" placeholder="Пошук..." oninput="filterPeople(this.value)"></div>
<table id="report"><thead><tr><th>Контакт</th><th>Компанія</th><th>Email</th><th>Статус</th><th>Відповідь</th></tr></thead><tbody>
{% for inv in invites %}<tr><td><b>{{ inv.contact.name }}</b><div class="muted">{{ inv.contact.position }}</div></td><td>{{ inv.contact.company }}</td><td>{{ inv.contact.email }}</td><td><span class="tag {% if not inv.sent_at %}unsent{% else %}{{ inv.status }}{% endif %}">{{ status_label(inv) }}</span></td>
<td>{% if inv.sent_at %}<a class="btn secondary small" href="{{ url_for('rsvp', token=inv.token) }}">Форма відповіді →</a>{% else %}<span class="muted">Спершу розсилка</span>{% endif %}</td></tr>{% endfor %}
</tbody></table></div>
<div class="section card"><h3>Журнал операцій</h3><div class="muted">Змодельованих повідомлень: {{ logs|length }}</div>
<div class="tablewrap"><table><thead><tr><th>Час (UTC)</th><th>Операція</th><th>Контакт</th></tr></thead><tbody>
{% for log in logs %}<tr><td>{{ log.created_at.strftime("%d.%m.%Y %H:%M") }}</td><td>{{ {"invitation":"Імітація запрошення","pending":"Імітація нагадування","accepted":"Імітація нагадування підтвердженому","real_test":"Реальний тестовий email"}.get(log.kind,log.kind) }}</td><td>{{ names.get(log.contact_id,"—") }}</td></tr>
{% else %}<tr><td colspan="3">Поки операцій немає</td></tr>{% endfor %}</tbody></table></div></div>
<script>function filterPeople(v){document.querySelectorAll("#report tbody tr").forEach(function(tr){tr.style.display=tr.innerText.toLowerCase().includes(v.toLowerCase())?"":"none"})}</script>
"""
@app.post("/test/create")
def create_personal_test():
    recipient = os.environ.get("TEST_RECIPIENT_EMAIL", "").strip().lower()
    if not EMAIL_RE.fullmatch(recipient):
        flash("Спочатку налаштуйте TEST_RECIPIENT_EMAIL у Render.", "error")
        return redirect(url_for("dashboard"))
    contact = Contact.query.filter_by(email=recipient).first()
    if contact is None:
        # This email comes only from the Render environment, never from an untrusted form.
        contact = Contact(name="Тестовий учасник", company="Персональний тест",
                          email=recipient, position="", phone="", region="")
        db.session.add(contact)
        db.session.flush()
    start = (datetime.now(ZoneInfo("Europe/Kyiv")) + timedelta(days=7)).strftime("%Y-%m-%dT10:00")
    event = Event(title="Тестова розсилка Event Assistant",
                  starts_at=start, location="Онлайн",
                  description="Перевірка реального email, персонального запрошення та підтвердження участі.")
    db.session.add(event)
    db.session.flush()
    db.session.add(Invitation(event_id=event.id, contact_id=contact.id))
    db.session.commit()
    flash("Створено персональний тест лише для одного учасника. Натисніть «Тестовий email» для наступного кроку.", "success")
    return redirect(url_for("event_detail", event_id=event.id))


@app.get("/events/<int:event_id>")
def event_detail(event_id):
    event = db.get_or_404(Event, event_id)
    invites = sorted(event.invitations, key=lambda x: (x.contact.company, x.contact.name))
    total = len(invites)
    accepted = sum(x.status == "accepted" and x.sent_at is not None for x in invites)
    declined = sum(x.status == "declined" and x.sent_at is not None for x in invites)
    pending = sum(x.status == "pending" and x.sent_at is not None for x in invites)
    unsent = sum(x.sent_at is None for x in invites)
    logs = MessageLog.query.filter_by(event_id=event_id).order_by(MessageLog.id.desc()).limit(30).all()
    return page("Управління заходом", EVENT_DETAIL, event=event, invites=invites, total=total,
                accepted=accepted, declined=declined, pending=pending, unsent=unsent,
                accepted_pct=round(accepted / total * 100, 2) if total else 0,
                declined_pct=round(declined / total * 100, 2) if total else 0,
                status_label=status_label, logs=logs,
                names={x.contact_id: x.contact.name for x in invites})

SEND_CONFIRM = """
<div class="card" style="max-width:720px">
  <h2>Підтвердження імітації розсилки</h2>
  <p><b>{{ event.title }}</b></p>
  {% if unsent > 0 %}
  <div class="note">Запрошення будуть позначені як відправлені для {{ unsent }} учасників. Жоден реальний email не надсилатиметься.</div>
  <div class="spacer"></div>
  <form method="post" action="{{ url_for('event_send', event_id=event.id) }}">
    <input type="hidden" name="_csrf" value="{{ csrf }}">
    <div class="actions">
      <button type="submit" class="btn">✓ Підтвердити імітацію ({{ unsent }})</button>
      <a class="btn secondary" href="{{ url_for('event_detail', event_id=event.id) }}">Повернутися</a>
    </div>
  </form>
  {% else %}
  <p class="note">Усі запрошення цього заходу вже позначені як відправлені. Повторна імітація не потрібна.</p>
  <a class="btn secondary" href="{{ url_for('event_detail', event_id=event.id) }}">Повернутися до звіту</a>
  {% endif %}
</div>
"""

@app.route("/events/<int:event_id>/send", methods=["GET","POST"])
def event_send(event_id):
    event = db.get_or_404(Event, event_id)
    if request.method == "GET":
        unsent = sum(1 for inv in event.invitations if inv.sent_at is None)
        return page("Імітація розсилки", SEND_CONFIRM, event=event, unsent=unsent)
    count = 0
    for inv in event.invitations:
        if inv.sent_at is None:
            inv.sent_at = utcnow()
            db.session.add(MessageLog(event_id=event_id, contact_id=inv.contact_id, kind="invitation"))
            count += 1
    db.session.commit()
    flash("Імітовано відправку запрошень: " + str(count), "success")
    return redirect(url_for("event_detail", event_id=event_id))

REAL_TEST_CONFIRM = """
<div class="card" style="max-width:720px">
  <h2>Справжній тестовий лист</h2>
  <p><b>{{ event.title }}</b></p>
  {% if not configured %}
  <div class="note">Пошту ще не підключено. В налаштуваннях Render для цього вебсервісу потрібно додати <code>RESEND_API_KEY</code> і <code>TEST_RECIPIENT_EMAIL</code>. Ключ зберігайте тільки у Render, не в коді GitHub.</div>
  {% elif not inv %}
  <div class="note">У цьому заході немає учасника з дозволеною адресою тестування. Переконайтеся, що контакт із email, який указаний у <code>TEST_RECIPIENT_EMAIL</code>, доданий до заходу.</div>
  {% elif already_sent %}
  <div class="note">Справжній тестовий лист цьому учаснику в межах цього заходу вже надіслано. Повторне надсилання заблоковано, щоб уникнути дублікатів. Для нового тесту створіть новий захід.</div>
  {% else %}
  <div class="note">Після підтвердження Resend відправить <b>ОДИН реальний лист</b> на <b>{{ inv.contact.email }}</b>. У листі буде особисте посилання для підтвердження участі. Іншим учасникам листи не надсилатимуться.</div>
  <div class="spacer"></div>
  <form method="post" action="{{ url_for('send_test_email', event_id=event.id) }}">
    <input type="hidden" name="_csrf" value="{{ csrf }}">
    <div class="actions">
      <button type="submit" class="btn gold">✓ Надіслати один тестовий лист</button>
      <a class="btn secondary" href="{{ url_for('event_detail',event_id=event.id) }}">Скасувати</a>
    </div>
  </form>
  {% endif %}
  <div class="spacer"></div>
  <a class="btn secondary" href="{{ url_for('event_detail',event_id=event.id) }}">Повернутися до заходу</a>
</div>
"""

@app.route("/events/<int:event_id>/test-email", methods=["GET", "POST"])
def send_test_email(event_id):
    event = db.get_or_404(Event, event_id)
    allow_address = os.environ.get("TEST_RECIPIENT_EMAIL", "").strip().lower()
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    configured = bool(api_key and EMAIL_RE.fullmatch(allow_address))
    invite = next((i for i in event.invitations if i.contact.email.lower() == allow_address), None) if configured else None
    already_sent = bool(invite and MessageLog.query.filter_by(event_id=event_id, contact_id=invite.contact_id, kind="real_test").first())
    if request.method == "GET":
        return page("Тестова пошта", REAL_TEST_CONFIRM, event=event, inv=invite, configured=configured, already_sent=already_sent)
    if not configured or invite is None:
        flash("Спершу налаштуйте Resend і додайте дозволену адресу до учасників заходу.", "error")
        return redirect(url_for("send_test_email", event_id=event_id))
    if already_sent:
        flash("Цей тестовий лист уже надсилали. Створіть новий захід для повторної перевірки.", "error")
        return redirect(url_for("send_test_email", event_id=event_id))
    # Server-side allowlist. Never send bulk email from the demo.
    if invite.contact.email.lower() != allow_address:
        abort(403)
    import resend
    resend.api_key = api_key
    base_url = os.environ.get("PUBLIC_BASE_URL", "https://event-assistant-demo.onrender.com").rstrip("/")
    link = base_url + url_for("rsvp", token=invite.token)
    subject = ("Запрошення: " + event.title)[:250]
    recipient_name = html.escape(invite.contact.name)
    title = html.escape(event.title)
    date = html.escape(event_date(event.starts_at))
    place = html.escape(event.location or "Місце уточнюється")
    description = html.escape(event.description or "").replace("\n", "<br>")
    email_html = (
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#192841">'
        '<h2>Запрошення на захід</h2><p>Вітаємо, <b>' + recipient_name + '</b>!</p>'
        '<p>Запрошуємо вас на <b>' + title + '</b>.</p>'
        '<p><b>Дата:</b> ' + date + '<br><b>Місце:</b> ' + place + '</p>'
        '<p>' + description + '</p>'
        '<p><a href="' + html.escape(link, quote=True) + '" '
        'style="display:inline-block;background:#1b4f96;color:white;padding:14px 20px;border-radius:8px;text-decoration:none">'
        'Підтвердити або відхилити участь</a></p>'
        '<p style="font-size:12px;color:#6d7d93">Тестове запрошення Event Assistant.</p></div>'
    )
    try:
        response = resend.Emails.send({
            "from": os.environ.get("EMAIL_FROM", "Event Assistant <onboarding@resend.dev>"),
            "to": [allow_address],
            "subject": subject,
            "html": email_html,
        })
        email_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        if not email_id:
            raise RuntimeError("Provider response did not contain a message ID")
    except Exception as error:
        # Report the provider's actual error instead of guessing that a recipient is invalid.
        # Never disclose the Resend API key or an email address in logs or the UI.
        error_type = type(error).__name__
        status = getattr(error, "status_code", None)
        raw_reason = str(getattr(error, "message", None) or str(error) or "Причину не вказано")
        raw_reason = raw_reason.replace(api_key, "[секрет приховано]")
        raw_reason = re.sub(r"\b(?:re_|sk_)[A-Za-z0-9_-]{6,}\b", "[секрет приховано]", raw_reason)
        raw_reason = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email приховано]", raw_reason)
        raw_reason = re.sub(r"https?://\S+", "[посилання приховано]", raw_reason)
        safe_reason = " ".join(raw_reason.split())[:350]
        label = error_type + ((" HTTP " + str(status)) if status else "")
        app.logger.warning("Real test email failed: %s: %s", label, safe_reason)
        flash("Помилка тестового email (" + label + "): " + safe_reason, "error")
        return redirect(url_for("send_test_email", event_id=event_id))
    db.session.add(MessageLog(event_id=event_id, contact_id=invite.contact_id, kind="real_test"))
    if invite.sent_at is None:
        invite.sent_at = utcnow()
    db.session.commit()
    flash("Resend прийняв один тестовий лист для відправлення. Перевірте пошту (також папку Спам) та натисніть на посилання участі.", "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<int:event_id>/remind")
def event_remind(event_id):
    event = db.get_or_404(Event, event_id)
    audience = request.form.get("audience")
    if audience not in {"pending", "accepted"}:
        abort(400)
    count = 0
    for inv in event.invitations:
        if inv.sent_at is not None and inv.status == audience:
            db.session.add(MessageLog(event_id=event_id, contact_id=inv.contact_id, kind=audience))
            count += 1
    db.session.commit()
    flash("Імітовано нагадувань: " + str(count), "success")
    return redirect(url_for("event_detail", event_id=event_id))

def report_rows(event_id):
    event = db.get_or_404(Event, event_id)
    headings = ["Захід","Дата заходу","Контакт","Компанія","Посада","Email","Телефон","Регіон","Статус","Дата відповіді (UTC)"]
    rows = []
    for inv in sorted(event.invitations, key=lambda x:x.contact.name):
        c = inv.contact
        rows.append([event.title,event_date(event.starts_at),c.name,c.company,c.position,c.email,c.phone,c.region,
                     status_label(inv),inv.responded_at.strftime("%Y-%m-%d %H:%M") if inv.responded_at else ""])
    return headings, rows

@app.get("/events/<int:event_id>/export.xlsx")
def event_export(event_id):
    headings, rows = report_rows(event_id)
    book = Workbook()
    sheet = book.active
    sheet.title = "Учасники"
    sheet.append(headings)
    for row in rows:
        sheet.append([("'" + value) if isinstance(value,str) and value.startswith(("=","+","-","@")) else value for value in row])
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    return send_file(stream, as_attachment=True, download_name="event_" + str(event_id) + "_report.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/events/<int:event_id>/export.csv")
def event_csv(event_id):
    headings, rows = report_rows(event_id)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headings)
    writer.writerows([("'" + value) if isinstance(value,str) and value.startswith(("=","+","-","@")) else value for value in row] for row in rows)
    response = make_response("\ufeff" + stream.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=event_" + str(event_id) + "_report.csv"
    return response

RSVP = """
<div class="card" style="max-width:650px;margin:auto">
<p class="eyebrow">Персональне запрошення</p><h2>{{ event.title }}</h2>
<p class="muted">Дата: <b>{{ event.starts_at|event_date }}</b><br>Місце: <b>{{ event.location or "Буде уточнено" }}</b></p>
<p>{{ event.description }}</p><hr style="border:0;border-top:1px solid #edf0f4;margin:22px 0">
<p>Вітаємо, <b>{{ contact.name }}</b>! Просимо підтвердити вашу участь.</p>
{% if inv.status != "pending" %}<p class="note">Поточна відповідь: <b>{{ status_label(inv) }}</b>. Ви можете змінити її нижче.</p>{% endif %}
<form method="post" class="actions"><button class="btn" name="decision" value="accepted">✓ Беру участь</button>
<button class="btn secondary" name="decision" value="declined">✕ Не зможу</button></form>
<p class="muted">Ваше рішення миттєво з'явиться у звіті організатора. Це демонстраційна форма.</p></div>
"""
@app.route("/rsvp/<token>", methods=["GET", "POST"])
def rsvp(token):
    inv = Invitation.query.filter_by(token=token).first_or_404()
    if inv.sent_at is None:
        abort(404)
    if request.method == "POST":
        decision = request.form.get("decision")
        if decision not in {"accepted", "declined"}:
            abort(400)
        inv.status = decision
        inv.responded_at = utcnow()
        db.session.commit()
        flash("Дякуємо! Вашу відповідь збережено.", "success")
        return redirect(url_for("rsvp", token=token))
    return page("Підтвердження участі", RSVP, inv=inv, event=inv.event, contact=inv.contact, status_label=status_label)

def seed_demo():
    if Contact.query.count():
        return
    companies = ["АгроПартнер","Фермер-Сервіс","АгроЛідер","Зелений Простір","Схід-Агро","Поля України"]
    regions = ["Кіровоградська","Полтавська","Черкаська","Вінницька","Київська","Дніпропетровська"]
    first = ["Олександр","Ірина","Дмитро","Катерина","Андрій","Наталія"]
    last = ["Коваленко","Шевченко","Мельник","Бондар","Ткаченко","Петренко"]
    contacts = []
    for index in range(36):
        contact = Contact(name=first[index%6]+" "+last[(index//6+index)%6],company=companies[index%6],
                          position="Менеджер із продажів" if index%3 else "Керівник напрямку",
                          region=regions[index%6],email="participant%02d@example.com"%(index+1),
                          phone="")
        db.session.add(contact)
        contacts.append(contact)
    db.session.flush()
    event = Event(title="Демонстраційне навчання партнерів", starts_at="2026-12-18T10:00",
                  location="Кропивницький · конференц-зал",description="Огляд продуктів, практичні кейси та обговорення.")
    db.session.add(event)
    db.session.flush()
    for i,c in enumerate(contacts):
        s = "accepted" if i<24 else "declined" if i<28 else "pending"
        db.session.add(Invitation(event_id=event.id,contact_id=c.id,status=s,
                                  sent_at=utcnow()-timedelta(days=1),
                                  responded_at=utcnow() if s!="pending" else None))
    db.session.commit()

with app.app_context():
    db.create_all()
    seed_demo()

if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)), host="0.0.0.0")
