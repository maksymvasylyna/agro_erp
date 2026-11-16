"""Administrator session gate for AgroERP administrative actions.

Current scope is permanent field deletion. Future permissions for whole
reference directories can reuse admin_required and is_admin.
"""
import hashlib
import hmac
import threading
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_wtf import FlaskForm
from wtforms import PasswordField, SubmitField
from wtforms.validators import DataRequired

admin_bp = Blueprint("admin_auth", __name__, url_prefix="/admin")

# Basic per-process protection. Replace with a shared rate limiter when
# multi-user role-based authorization is introduced.
_attempts = {}
_attempt_lock = threading.Lock()
_LIMIT = 5
_WINDOW = 900


class AdminLoginForm(FlaskForm):
    password = PasswordField("Пароль адміністратора", validators=[DataRequired()])
    submit = SubmitField("Увійти")


class AdminLogoutForm(FlaskForm):
    pass


def _admin_password():
    candidate = current_app.config.get("ADMIN_PASSWORD")
    return candidate if isinstance(candidate, str) and len(candidate) >= 16 else None


def _secure_key():
    key = current_app.config.get("SECRET_KEY")
    if isinstance(key, bytes):
        key = key.decode("utf-8", "ignore")
    return key if isinstance(key, str) and len(key) >= 32 and key not in ("dev-key", "dev-change-me") else None


def _auth_tag():
    password, secret = _admin_password(), _secure_key()
    if not password or not secret:
        return None
    return hmac.new(
        secret.encode("utf-8"), b"AgroERP-admin-v1:" + password.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def is_admin():
    expected = _auth_tag()
    actual = session.get("agroerp_admin")
    return bool(expected and isinstance(actual, str) and hmac.compare_digest(actual, expected))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            if request.method == "GET":
                return redirect(url_for("admin_auth.login", next=request.full_path.rstrip("?")))
            abort(403, description="Лише адміністратор може виконати цю операцію.")
        return view(*args, **kwargs)
    return wrapper


def _safe_next(raw):
    parsed = urlsplit(raw or "")
    if (not raw or parsed.scheme or parsed.netloc or parsed.fragment
            or not parsed.path.startswith("/") or parsed.path.startswith("//")
            or "\\" in raw or "\x00" in raw):
        return url_for("fields.index")
    return raw


def _client_key():
    return request.remote_addr or "unknown"


def _locked():
    address, now = _client_key(), time.monotonic()
    with _attempt_lock:
        recent = [t for t in _attempts.get(address, ()) if now-t < _WINDOW]
        if recent:
            _attempts[address] = recent
        else:
            _attempts.pop(address, None)
        return len(recent) >= _LIMIT


def _failed():
    address, now = _client_key(), time.monotonic()
    with _attempt_lock:
        _attempts[address] = [t for t in _attempts.get(address, ()) if now-t < _WINDOW] + [now]


def _clear_failed():
    with _attempt_lock:
        _attempts.pop(_client_key(), None)


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if is_admin():
        return redirect(_safe_next(request.values.get("next")))
    form = AdminLoginForm()
    enabled = bool(_auth_tag())
    next_target = _safe_next(request.form.get("next") if request.method == "POST" else request.args.get("next"))
    if request.method == "POST":
        if not form.validate_on_submit():
            abort(400, description="Недійсна форма авторизації.")
        if not enabled:
            abort(403, description="Адміністративний вхід не налаштовано.")
        if _locked():
            flash("Забагато спроб входу. Спробуйте пізніше.", "warning")
            return render_template("admin/login.html", form=form, enabled=enabled, next_target=next_target), 429
        if not hmac.compare_digest(form.password.data or "", _admin_password()):
            _failed()
            flash("Неправильний пароль.", "warning")
        else:
            _clear_failed()
            session.clear()
            session.permanent = True
            session["agroerp_admin"] = _auth_tag()
            return redirect(next_target)
    return render_template("admin/login.html", form=form, enabled=enabled, next_target=next_target)


@admin_bp.post("/logout")
def logout():
    if not AdminLogoutForm().validate_on_submit():
        abort(400, description="Недійсна форма виходу.")
    session.clear()
    flash("Ви вийшли з режиму адміністратора.", "info")
    return redirect(url_for("index"))
