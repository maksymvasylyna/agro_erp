import sys, os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from flask import Flask, render_template, flash, redirect, request, url_for
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlparse
from config import Config
from extensions import db
from register_blueprints import register_blueprints

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "dev-change-me"  # щоб flash точно працював у dev

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    register_blueprints(app)

    @app.context_processor
    def inject_harvest_seasons():
        # Shared year selector on every page, not only seasonal blueprint routes.
        from flask import session
        from modules.structure.seasons.models import Season
        years = Season.query.order_by(Season.year.desc()).all()
        active = session.get("harvest_year")
        if active not in {s.year for s in years}:
            active = years[0].year if years else None
        return {"available_seasons": years, "active_harvest_year": active}

    # Імпорт моделей (зв’язки)
    from modules.reference.products.models import Product
    from modules.reference.categories.models import Category
    from modules.reference.units.models import Unit
    from modules.reference.groups.models import Group
    from modules.reference.manufacturers.models import Manufacturer
    from modules.reference.payers.models import Payer
    from modules.reference.currencies.models import Currency
    from modules.reference.clusters.models import Cluster
    from modules.reference.cultures.models import Culture
    from modules.reference.companies.models import Company
    from modules.reference.fields.field_models import Field
    from modules.structure.seasons.models import Season, FieldSeason, FieldPlanting

    with app.app_context():
        db.create_all()

    # Only staging hosts historical source data and requires a viewer password.
    # Production behavior is unchanged when AGROERP_ENV is not staging.
    if os.getenv("AGROERP_ENV") == "staging":
        from datetime import timedelta
        from hmac import compare_digest
        from flask import session
        from flask_wtf import FlaskForm
        from wtforms import PasswordField, SubmitField
        from wtforms.validators import DataRequired

        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        )

        class StagingAccessForm(FlaskForm):
            password = PasswordField("Пароль доступу", validators=[DataRequired()])
            submit = SubmitField("Увійти")

        @app.before_request
        def require_staging_access():
            if request.endpoint == "staging_login":
                return None
            password = os.getenv("STAGING_VIEW_PASSWORD", "")
            if len(password) < 16:
                return "Test site access is disabled: viewer password not configured.", 503
            if session.get("staging_view") is True:
                return None
            return redirect(url_for("staging_login", next=request.path))

        @app.route("/staging-login", methods=["GET", "POST"])
        def staging_login():
            form = StagingAccessForm()
            if form.validate_on_submit():
                expected = os.getenv("STAGING_VIEW_PASSWORD", "")
                if len(expected) >= 16 and compare_digest(
                    form.password.data.encode("utf-8"), expected.encode("utf-8")
                ):
                    session.clear()
                    session.permanent = True
                    session["staging_view"] = True
                    destination = request.args.get("next", "")
                    if not (destination.startswith("/") and not destination.startswith("//")
                            and "\\\\" not in destination):
                        destination = url_for("seasonal.index")
                    return redirect(destination)
                flash("Невірний пароль.", "danger")
            return render_template("staging_login.html", form=form)

    @app.route('/')
    def index():
        return render_template('index.html')

    # ── куди редіректити після помилки
    def _safe_redirect_target() -> str:
        path = (request.path or "").lower()
        if any(seg in path for seg in ("/create", "/edit")):
            return request.path  # GET на ту ж форму
        ref = request.referrer
        if ref:
            ref_netloc = urlparse(ref).netloc
            if not ref_netloc or ref_netloc == request.host:
                return ref
        return url_for('index')

    # ── єдиний обробник IntegrityError
    def _integrity_error_handler(e):
        db.session.rollback()
        msg = str(getattr(e, "orig", e))
        app.logger.warning(f"IntegrityError caught: {msg}")  # ✅ побачиш у консолі

        if "UNIQUE constraint failed" in msg:
            flash('Запис з такою назвою вже існує.', 'warning')
            return redirect(_safe_redirect_target()), 303
        if "FOREIGN KEY constraint failed" in msg:
            flash('Операція неможлива: запис використовується в інших даних.', 'warning')
            return redirect(_safe_redirect_target()), 303

        flash('Порушення цілісності даних. Перевірте унікальність та звʼязки.', 'warning')
        return redirect(_safe_redirect_target()), 303

    # ✅ ЯВНО реєструємо (працює для всіх blueprint’ів)
    app.register_error_handler(IntegrityError, _integrity_error_handler)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5001, debug=True)
