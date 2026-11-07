"""Seasonal crop structure, isolated from legacy field columns.

Write actions are disabled unless an admin password and a strong Flask SECRET_KEY
are configured. All mutating forms use Flask-WTF CSRF validation.
"""
import os
from decimal import Decimal, InvalidOperation
from hmac import compare_digest
from urllib.parse import urlsplit

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_wtf import FlaskForm
from wtforms import DecimalField, IntegerField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from . import seasonal_bp
from .models import FieldPlanting, FieldSeason, Season


class LoginForm(FlaskForm):
    password = PasswordField("Пароль адміністратора", validators=[DataRequired()])
    submit = SubmitField("Увійти")


class SeasonForm(FlaskForm):
    year = IntegerField("Рік урожаю", validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    submit = SubmitField("Створити сезон")


class FieldSeasonForm(FlaskForm):
    field_id = SelectField("Поле", coerce=int, validators=[DataRequired()])
    area = DecimalField("Площа поля, га", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    submit = SubmitField("Додати поле")


class PlantingForm(FlaskForm):
    culture_id = SelectField("Культура", coerce=int, validators=[DataRequired()])
    area = DecimalField("Площа культури, га", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    note = StringField("Примітка", validators=[Optional()])
    submit = SubmitField("Додати посів")


class CopyForm(FlaskForm):
    submit = SubmitField("Скопіювати попередній сезон")


def _is_admin():
    password = os.getenv("SEASON_ADMIN_PASSWORD", "")
    key = current_app.config.get("SECRET_KEY", "")
    return (len(password) >= 16
            and isinstance(key, str) and len(key) >= 32
            and key not in ("dev-key", "dev-change-me")
            and session.get("season_editor") is True)


def _require_admin():
    if not _is_admin():
        abort(403, description="Season editing requires a configured admin login.")


def _valid_configuration():
    password = os.getenv("SEASON_ADMIN_PASSWORD", "")
    key = current_app.config.get("SECRET_KEY", "")
    return len(password) >= 16 and isinstance(key, str) and len(key) >= 32 and key not in ("dev-key", "dev-change-me")


@seasonal_bp.app_context_processor
def season_context():
    seasons = Season.query.order_by(Season.year.desc()).all()
    year = session.get("harvest_year")
    allowed = {s.year for s in seasons}
    if year not in allowed:
        year = seasons[0].year if seasons else None
    return {"available_seasons": seasons, "active_harvest_year": year}


@seasonal_bp.route("/select")
def select():
    try:
        year = int(request.args.get("year", "0"))
    except ValueError:
        abort(400)
    if not Season.query.filter_by(year=year).first():
        abort(404)
    session["harvest_year"] = year

    # Keep the current report and its filters when changing seasons.
    # Only a local path is accepted to prevent open redirects.
    next_path = request.args.get("next", "", type=str)
    target = urlsplit(next_path)
    is_safe = (
        target.scheme == "" and target.netloc == "" and target.fragment == ""
        and target.path.startswith("/") and not target.path.startswith("//")
        and "\\\\" not in next_path and "\\x00" not in next_path
        and target.path != url_for("seasonal.select")
    )
    if is_safe:
        return redirect(next_path)
    return redirect(url_for("seasonal.index"))


@seasonal_bp.route("/login", methods=["GET", "POST"])
def login():
    if not _valid_configuration():
        abort(503, description="Season editing is disabled until administrator secrets are configured.")
    form = LoginForm()
    if form.validate_on_submit():
        expected = os.environ["SEASON_ADMIN_PASSWORD"]
        if compare_digest(form.password.data.encode("utf-8"), expected.encode("utf-8")):
            session.clear()
            session["season_editor"] = True
            flash("Доступ до редагування сезонів відкрито.", "success")
            return redirect(url_for("seasonal.index"))
        flash("Невірний пароль.", "danger")
    return render_template("seasons/login.html", form=form)


@seasonal_bp.route("/logout", methods=["POST"])
def logout():
    form = FlaskForm()
    if not form.validate_on_submit():
        abort(400)
    year = session.get("harvest_year")
    session.clear()
    if year:
        session["harvest_year"] = year
    return redirect(url_for("seasonal.index"))


@seasonal_bp.route("/")
def index():
    year = request.args.get("year", type=int) or session.get("harvest_year")
    seasons = Season.query.order_by(Season.year.desc()).all()
    season = next((s for s in seasons if s.year == year), None)
    if season is None and seasons:
        season = seasons[0]
    if season:
        year = season.year
        session["harvest_year"] = year
    rows = (FieldSeason.query.filter_by(season_id=season.id)
            .order_by(FieldSeason.company_id, FieldSeason.field_id).all()) if season else []
    planted = sum((entry.planted_area for entry in rows), Decimal("0.00"))
    total = sum((entry.area for entry in rows), Decimal("0.00"))
    new_form = SeasonForm(prefix="new")
    field_form = FieldSeasonForm(prefix="field")
    field_form.field_id.choices = [
        (f.id, f"{f.name} — {f.company.name if f.company else '—'}")
        for f in Field.query.filter_by(is_active=True).order_by(Field.name).all()
    ]
    planting_form = PlantingForm(prefix="plant")
    planting_form.culture_id.choices = [(c.id, c.name) for c in Culture.query.order_by(Culture.name).all()]
    return render_template(
        "seasons/index.html", seasons=seasons, season=season, rows=rows,
        total=total, planted=planted, new_form=new_form,
        field_form=field_form, planting_form=planting_form,
        copy_form=CopyForm(), logout_form=FlaskForm(), action_form=FlaskForm(),
        can_edit=_is_admin(), editor_enabled=_valid_configuration(),
    )


@seasonal_bp.route("/create", methods=["POST"])
def create():
    _require_admin()
    form = SeasonForm(prefix="new")
    if not form.validate_on_submit():
        abort(400)
    if Season.query.filter_by(year=form.year.data).first():
        flash("Сезон уже існує.", "warning")
    else:
        db.session.add(Season(year=form.year.data))
        db.session.commit()
        flash(f"Створено сезон урожаю {form.year.data}.", "success")
    return redirect(url_for("seasonal.index", year=form.year.data))


@seasonal_bp.route("/<int:year>/fields", methods=["POST"])
def add_field(year):
    _require_admin()
    season = Season.query.filter_by(year=year).first_or_404()
    if season.is_closed:
        abort(409)
    form = FieldSeasonForm(prefix="field")
    form.field_id.choices = [(f.id, f.name) for f in Field.query.filter_by(is_active=True).all()]
    if not form.validate_on_submit():
        abort(400)
    field = Field.query.filter_by(id=form.field_id.data, is_active=True).first_or_404()
    if not field.company_id or not field.cluster_id:
        abort(400, description="Field needs a company and cluster.")
    if FieldSeason.query.filter_by(field_id=field.id, season_id=season.id).first():
        flash("Поле вже є у вибраному сезоні.", "warning")
    else:
        db.session.add(FieldSeason(
            season_id=season.id, field_id=field.id, company_id=field.company_id,
            cluster_id=field.cluster_id, area=form.area.data,
        ))
        db.session.commit()
        flash("Поле додано до сезону.", "success")
    return redirect(url_for("seasonal.index", year=year))


@seasonal_bp.route("/fields/<int:field_season_id>/plantings", methods=["POST"])
def add_planting(field_season_id):
    _require_admin()
    fs = FieldSeason.query.get_or_404(field_season_id)
    if fs.season.is_closed:
        abort(409)
    form = PlantingForm(prefix="plant")
    form.culture_id.choices = [(c.id, c.name) for c in Culture.query.all()]
    if not form.validate_on_submit():
        abort(400)
    if fs.planted_area + form.area.data > fs.area:
        flash("Посівна площа перевищує площу поля.", "danger")
    else:
        db.session.add(FieldPlanting(
            field_season_id=fs.id, culture_id=form.culture_id.data,
            area=form.area.data, note=(form.note.data or "").strip() or None,
        ))
        db.session.commit()
        flash("Посів додано.", "success")
    return redirect(url_for("seasonal.index", year=fs.season.year))


@seasonal_bp.route("/<int:year>/copy", methods=["POST"])
def copy_previous(year):
    _require_admin()
    form = CopyForm()
    if not form.validate_on_submit():
        abort(400)
    target = Season.query.filter_by(year=year).first_or_404()
    source = Season.query.filter_by(year=year - 1).first_or_404()
    if target.is_closed:
        abort(409)
    if FieldSeason.query.filter_by(season_id=target.id).first():
        abort(409, description="Target season must be empty.")
    for fs in FieldSeason.query.filter_by(season_id=source.id).all():
        new_fs = FieldSeason(
            season_id=target.id, field_id=fs.field_id, company_id=fs.company_id,
            cluster_id=fs.cluster_id, area=fs.area,
        )
        db.session.add(new_fs)
        db.session.flush()
        for planting in fs.plantings:
            db.session.add(FieldPlanting(
                field_season_id=new_fs.id, culture_id=planting.culture_id,
                area=planting.area, note=planting.note,
            ))
    db.session.commit()
    flash(f"Структуру {year-1} скопійовано в {year}. Змініть культури за потреби.", "success")
    return redirect(url_for("seasonal.index", year=year))


@seasonal_bp.route("/plantings/<int:planting_id>/edit", methods=["GET", "POST"])
def edit_planting(planting_id):
    _require_admin()
    planting = FieldPlanting.query.get_or_404(planting_id)
    fs = planting.field_season
    if fs.season.is_closed:
        abort(409)
    form = PlantingForm(prefix="plant", obj=planting)
    form.culture_id.choices = [(c.id, c.name) for c in Culture.query.order_by(Culture.name).all()]
    if form.validate_on_submit():
        other_area = fs.planted_area - planting.area
        if other_area + form.area.data > fs.area:
            flash("Сума посівів перевищить площу поля.", "danger")
        else:
            planting.culture_id = form.culture_id.data
            planting.area = form.area.data
            planting.note = (form.note.data or "").strip() or None
            db.session.commit()
            flash("Посів оновлено.", "success")
            return redirect(url_for("seasonal.index", year=fs.season.year))
    elif request.method == "GET":
        form.culture_id.data = planting.culture_id
    return render_template("seasons/edit_planting.html", form=form, planting=planting)


@seasonal_bp.route("/plantings/<int:planting_id>/delete", methods=["POST"])
def delete_planting(planting_id):
    _require_admin()
    if not FlaskForm().validate_on_submit():
        abort(400)
    planting = FieldPlanting.query.get_or_404(planting_id)
    year = planting.field_season.season.year
    if planting.field_season.season.is_closed:
        abort(409)
    db.session.delete(planting)
    db.session.commit()
    flash("Посів вилучено із сезону.", "success")
    return redirect(url_for("seasonal.index", year=year))


@seasonal_bp.route("/fields/<int:field_season_id>/area", methods=["POST"])
def update_field_area(field_season_id):
    _require_admin()
    fs = FieldSeason.query.get_or_404(field_season_id)
    if fs.season.is_closed:
        abort(409)
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        new_area = Decimal((request.form.get("area") or "").replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        abort(400)
    if not new_area.is_finite() or new_area <= 0 or new_area < fs.planted_area:
        flash("Площа має бути додатною та не меншою за суму посівів.", "danger")
    else:
        fs.area = new_area
        db.session.commit()
        flash("Площу поля в сезоні оновлено.", "success")
    return redirect(url_for("seasonal.index", year=fs.season.year))
