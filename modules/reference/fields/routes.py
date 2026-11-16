"""Field reference CRUD and authoritative seasonal crop rotation.

All new season-specific writes go to field_seasons/field_plantings. Old
fields.area / fields.culture_id remain unchanged by seasonal edits so the
existing 26 operational plans do not silently change interpretation.
"""
from decimal import Decimal
from admin_auth import admin_required
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_wtf import FlaskForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from modules.reference.fields.field_models import Field
from modules.reference.fields.forms import (
    ActionForm, FieldCreateForm, FieldNameForm, PlantingForm,
    SeasonCreateForm, SeasonFieldForm,
)
from modules.reference.fields.season_models import FieldPlanting, FieldSeason, Season
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture

fields_bp = Blueprint("fields", __name__, template_folder="templates")


def _context():
    seasons = Season.query.order_by(Season.year.desc()).all()
    selected = session.get("harvest_year")
    season = next((s for s in seasons if s.year == selected), None)
    if season is None:
        season = seasons[0] if seasons else None
    if season:
        session["harvest_year"] = season.year
    return seasons, season


def _view_context():
    seasons, season = _context()
    return {"seasons": seasons, "season": season, "active_year": season.year if season else None}


def _ensure_open(season):
    if season is None:
        abort(404, description="Спочатку створіть сезон у довіднику полів.")
    if season.is_closed:
        abort(409, description="Сезон закрито для редагування.")


def _valid_parent(form):
    if not form.company.data or not form.cluster.data:
        return False
    if form.company.data.cluster_id != form.cluster.data.id:
        form.company.errors.append("Це підприємство не належить до вибраного кластера.")
        return False
    return True


def _active_duplicate(name, company_id, exclude_id=None):
    query = Field.query.filter(
        Field.is_active.is_(True),
        Field.company_id == company_id,
        func.lower(Field.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(Field.id != exclude_id)
    return query.first()


def _season_fields(season_id):
    return (
        FieldSeason.query
        .options(
            joinedload(FieldSeason.field),
            joinedload(FieldSeason.company),
            joinedload(FieldSeason.cluster),
            selectinload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        )
        .filter(FieldSeason.season_id == season_id)
    )


def _safe_redirect_path(raw):
    parsed = urlsplit(raw or "")
    return (
        bool(raw) and parsed.scheme == "" and parsed.netloc == "" and parsed.fragment == ""
        and parsed.path.startswith("/") and not parsed.path.startswith("//")
        and chr(92) not in raw and chr(0) not in raw
        and parsed.path != url_for("fields.select_season")
    )


def _save_errors(form):
    messages = [message for errors in form.errors.values() for message in errors]
    flash(" ".join(messages) or "Перевірте дані форми.", "warning")


def _facet_selection(key, available_ids):
    """Read an inclusive multi-select; no parameter means all current choices.

    Never expand unknown IDs into "all", even if a stale URL is submitted.
    """
    available = set(available_ids)
    raw_values = request.args.getlist(key)
    if not raw_values:
        return sorted(available), available
    if "__none__" in raw_values:
        return [], set()
    selected = set()
    for raw in raw_values:
        try:
            value = int(raw)
        except (ValueError, TypeError):
            continue
        if value in available:
            selected.add(value)
    return sorted(selected), selected


def _facet_options(ids, model):
    if not ids:
        return []
    return model.query.filter(model.id.in_(ids)).order_by(model.name).all()


@fields_bp.route("/fields")
def index():
    ctx = _view_context()
    season = ctx["season"]
    term = (request.args.get("q") or "").strip()
    all_rows = []
    unassigned = []
    archived = Field.query.filter(Field.is_active.is_(False)).order_by(Field.name).all()

    if season:
        query = _season_fields(season.id).join(Field, FieldSeason.field_id == Field.id)
        if term:
            query = query.filter(Field.name.ilike(f"%{term}%"))
        all_rows = query.order_by(FieldSeason.company_id, Field.name).all()

        assigned = db.session.query(FieldSeason.field_id).filter(
            FieldSeason.season_id == season.id
        )
        unassigned = (
            Field.query.options(joinedload(Field.company))
            .filter(Field.is_active.is_(True), ~Field.id.in_(assigned))
            .order_by(Field.name)
            .all()
        )

    # Each facet contains only values represented in the selected season,
    # after applying the preceding filters (and optional field-number search).
    cluster_ids = {row.cluster_id for row in all_rows}
    selected_clusters, cluster_set = _facet_selection("cluster", cluster_ids)
    cluster_rows = [row for row in all_rows if row.cluster_id in cluster_set]

    company_ids = {row.company_id for row in cluster_rows}
    selected_companies, company_set = _facet_selection("company", company_ids)
    company_rows = [row for row in cluster_rows if row.company_id in company_set]

    culture_ids = {p.culture_id for row in company_rows for p in row.plantings}
    selected_cultures, culture_set = _facet_selection("culture", culture_ids)
    raw_cultures = request.args.getlist("culture")
    # Without an explicit crop restriction, retain unplanted seasonal fields.
    culture_is_filtered = bool(raw_cultures) and ("__none__" in raw_cultures or culture_set != culture_ids)
    rows = [
        row for row in company_rows
        if not culture_is_filtered or any(p.culture_id in culture_set for p in row.plantings)
    ]

    visible_plantings = {
        row.id: [
            p for p in row.plantings
            if not culture_is_filtered or p.culture_id in culture_set
        ]
        for row in rows
    }
    total = sum((row.area for row in rows), Decimal("0.00"))
    planted = sum(
        (p.area for plantings in visible_plantings.values() for p in plantings),
        Decimal("0.00"),
    )
    options = {
        "cluster": _facet_options(cluster_ids, Cluster),
        "company": _facet_options(company_ids, Company),
        "culture": _facet_options(culture_ids, Culture),
    }
    checked = {
        "cluster": selected_clusters,
        "company": selected_companies,
        "culture": selected_cultures,
    }
    context = dict(
        **ctx,
        rows=rows, unassigned=unassigned, archived=archived,
        total=total, planted=planted, term=term,
        visible_plantings=visible_plantings, options=options, checked=checked,
        create_url=url_for("fields.create"),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        html = render_template("fields/_results.html", **context)
        if request.accept_mimetypes.best == "application/json":
            return jsonify({
                "html": html,
                "options": {
                    key: [{"id": item.id, "name": item.name} for item in entries]
                    for key, entries in options.items()
                },
                "checked": checked,
            })
        return html
    return render_template("fields/index.html", **context)


@fields_bp.route("/fields/seasons")
def seasons_manager():
    ctx = _view_context()
    entries = []
    for item in ctx["seasons"]:
        entries.append({
            "season": item,
            "fields": FieldSeason.query.filter_by(season_id=item.id).count(),
            "previous": Season.query.filter_by(year=item.year - 1).first(),
        })
    return render_template(
        "fields/seasons.html", **ctx, entries=entries,
        new_form=SeasonCreateForm(prefix="new"),
        action_form=ActionForm(),
    )


@fields_bp.route("/fields/select-season")
def select_season():
    year = request.args.get("year", type=int)
    if year is None or not Season.query.filter_by(year=year).first():
        abort(404)
    session["harvest_year"] = year
    target = request.args.get("next", "")
    return redirect(target if _safe_redirect_path(target) else url_for("fields.index"))


@fields_bp.post("/fields/seasons/create")
def create_season():
    form = SeasonCreateForm(prefix="new")
    if not form.validate_on_submit():
        _save_errors(form)
        return redirect(url_for("fields.seasons_manager"))
    year = form.year.data
    if Season.query.filter_by(year=year).first():
        flash("Сезон цього року вже існує.", "warning")
    else:
        try:
            db.session.add(Season(year=year))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Не вдалося створити сезон: такий рік уже існує.", "warning")
        else:
            flash(f"Сезон урожаю {year} створено.", "success")
            session["harvest_year"] = year
    return redirect(url_for("fields.seasons_manager"))


@fields_bp.post("/fields/seasons/<int:year>/copy")
def copy_season(year):
    if not ActionForm().validate_on_submit():
        abort(400)
    target = Season.query.filter_by(year=year).first_or_404()
    source = Season.query.filter_by(year=year - 1).first()
    _ensure_open(target)
    if source is None:
        flash(f"Сезону {year - 1} не існує — копіювати нічого.", "warning")
    elif FieldSeason.query.filter_by(season_id=target.id).first():
        flash("Копіювати дозволено лише в повністю порожній сезон.", "warning")
    else:
        try:
            for row in _season_fields(source.id).all():
                dest = FieldSeason(
                    season_id=target.id, field_id=row.field_id, cluster_id=row.cluster_id,
                    company_id=row.company_id, area=row.area,
                )
                db.session.add(dest)
                db.session.flush()
                for planting in row.plantings:
                    db.session.add(FieldPlanting(
                        field_season_id=dest.id, culture_id=planting.culture_id,
                        area=planting.area, note=planting.note,
                    ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Копіювання зупинено через конфлікт даних.", "danger")
        else:
            flash(f"Сезон {year - 1} скопійовано в {year}. Перевірте культури та площі.", "success")
            session["harvest_year"] = year
    return redirect(url_for("fields.seasons_manager"))


@fields_bp.post("/fields/seasons/<int:year>/toggle")
def toggle_season(year):
    if not ActionForm().validate_on_submit():
        abort(400)
    season = Season.query.filter_by(year=year).first_or_404()
    season.is_closed = not season.is_closed
    db.session.commit()
    flash(
        f"Сезон {year} {'закрито' if season.is_closed else 'відкрито'} для редагування.",
        "info",
    )
    return redirect(url_for("fields.seasons_manager"))


@fields_bp.route("/fields/create", methods=["GET", "POST"])
def create():
    ctx = _view_context()
    season = ctx["season"]
    form = FieldCreateForm()
    companies = Company.query.order_by(Company.name).all()

    if form.validate_on_submit():
        _ensure_open(season)
        if not _valid_parent(form):
            pass
        elif _active_duplicate(form.name.data, form.company.data.id):
            form.name.errors.append("Поле з таким номером уже існує в цьому підприємстві.")
        else:
            field = Field(
                name=form.name.data, is_active=True,
                company_id=form.company.data.id, cluster_id=form.cluster.data.id,
                area=float(form.area.data),
                culture_id=form.culture.data.id if form.culture.data else None,
            )
            try:
                db.session.add(field)
                db.session.flush()
                record = FieldSeason(
                    season_id=season.id, field_id=field.id,
                    company_id=form.company.data.id, cluster_id=form.cluster.data.id,
                    area=form.area.data,
                )
                db.session.add(record)
                db.session.flush()
                if form.culture.data:
                    db.session.add(FieldPlanting(
                        field_season_id=record.id, culture_id=form.culture.data.id,
                        area=form.area.data,
                    ))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося створити поле: перевірте номер та зв'язки.")
            else:
                flash(f"Поле «{field.name}» створено у сезоні {season.year}.", "success")
                return redirect(url_for("fields.detail", id=field.id))
    return render_template(
        "fields/form.html", **ctx, form=form, companies=companies,
        view_mode="create", title="Створити поле",
    )


@fields_bp.route("/fields/<int:id>")
def detail(id):
    field = Field.query.get_or_404(id)
    ctx = _view_context()
    season = ctx["season"]
    record = (
        _season_fields(season.id).filter(FieldSeason.field_id == id).first()
        if season else None
    )
    field_form = SeasonFieldForm(prefix="field")
    if record:
        field_form.cluster.data = record.cluster
        field_form.company.data = record.company
        field_form.area.data = record.area
    else:
        field_form.cluster.data = field.cluster
        field_form.company.data = field.company
        field_form.area.data = Decimal(str(field.area)) if field.area else None
    plant_form = PlantingForm(prefix="plant")
    history = (
        FieldSeason.query.join(Season)
        .options(
            joinedload(FieldSeason.company), joinedload(FieldSeason.cluster),
            selectinload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        )
        .filter(FieldSeason.field_id == id)
        .order_by(Season.year.desc())
        .all()
    )
    return render_template(
        "fields/detail.html", **ctx, field=field, record=record,
        field_form=field_form, plant_form=plant_form,
        companies=Company.query.order_by(Company.name).all(),
        history=history, action_form=ActionForm(),
    )


@fields_bp.post("/fields/<int:id>/season")
def save_field_season(id):
    field = Field.query.get_or_404(id)
    _, season = _context()
    _ensure_open(season)
    form = SeasonFieldForm(prefix="field")
    if not form.validate_on_submit() or not _valid_parent(form):
        _save_errors(form)
        return redirect(url_for("fields.detail", id=field.id))
    record = FieldSeason.query.filter_by(season_id=season.id, field_id=field.id).first()
    if record and form.area.data < record.planted_area:
        flash("Фізична площа не може бути меншою за суму посівних площ.", "danger")
        return redirect(url_for("fields.detail", id=id))
    try:
        if record is None:
            record = FieldSeason(season_id=season.id, field_id=field.id)
            db.session.add(record)
        record.company_id = form.company.data.id
        record.cluster_id = form.cluster.data.id
        record.area = form.area.data
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Не вдалося зберегти поле в сезоні.", "danger")
    else:
        flash(f"Сезонні дані поля оновлено для {season.year} року.", "success")
    return redirect(url_for("fields.detail", id=id))


@fields_bp.post("/fields/<int:id>/plantings")
def add_planting(id):
    field = Field.query.get_or_404(id)
    _, season = _context()
    _ensure_open(season)
    record = FieldSeason.query.filter_by(season_id=season.id, field_id=field.id).first_or_404()
    form = PlantingForm(prefix="plant")
    if not form.validate_on_submit():
        _save_errors(form)
    elif record.planted_area + form.area.data > record.area:
        flash("Сума посівів перевищить фізичну площу поля.", "danger")
    else:
        try:
            db.session.add(FieldPlanting(
                field_season_id=record.id, culture_id=form.culture.data.id,
                area=form.area.data, note=(form.note.data or "").strip() or None,
            ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Не вдалося додати культуру до сівозміни.", "danger")
        else:
            flash("Посів додано.", "success")
    return redirect(url_for("fields.detail", id=field.id))


@fields_bp.route("/fields/plantings/<int:id>/edit", methods=["GET", "POST"])
def edit_planting(id):
    planting = FieldPlanting.query.get_or_404(id)
    record = planting.field_season
    _ensure_open(record.season)
    form = PlantingForm(prefix="plant", obj=planting)
    if form.validate_on_submit():
        if record.planted_area - planting.area + form.area.data > record.area:
            form.area.errors.append("Сума посівів перевищить фізичну площу.")
        else:
            planting.culture_id = form.culture.data.id
            planting.area = form.area.data
            planting.note = (form.note.data or "").strip() or None
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.area.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Посів оновлено.", "success")
                return redirect(url_for("fields.detail", id=record.field_id))
    return render_template(
        "fields/planting_form.html", form=form, planting=planting,
        parent_field=record.field, season=record.season,
    )


@fields_bp.post("/fields/plantings/<int:id>/delete")
def delete_planting(id):
    if not ActionForm().validate_on_submit():
        abort(400)
    planting = FieldPlanting.query.get_or_404(id)
    record = planting.field_season
    _ensure_open(record.season)
    field_id = record.field_id
    db.session.delete(planting)
    db.session.commit()
    flash("Посів видалено із сезону.", "info")
    return redirect(url_for("fields.detail", id=field_id))


@fields_bp.route("/fields/<int:id>/edit", methods=["GET", "POST"])
def edit(id):
    field = Field.query.get_or_404(id)
    form = FieldNameForm(obj=field)
    if form.validate_on_submit():
        if _active_duplicate(form.name.data, field.company_id, exclude_id=field.id):
            form.name.errors.append("Поле з таким номером уже існує в підприємстві.")
        else:
            field.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося перейменувати поле.")
            else:
                flash("Постійний номер поля оновлено.", "success")
                return redirect(url_for("fields.detail", id=id))
    return render_template("fields/form.html", form=form, view_mode="edit",
                           title="Редагувати номер поля", field=field)


def _permanent_delete_blocker(field):
    """Return a reason deletion is unsafe, or None for an unused field.

    Protect plans/purchases and cross-season history. Database FK constraints
    remain the final backstop for dependencies introduced by other modules.
    """
    from modules.plans.models import Plan
    from modules.purchases.payer_allocation.models import PayerAllocation

    if Plan.query.filter_by(field_id=field.id).first():
        return "Поле використовується у планах. Спочатку розберіться з планами або архівуйте поле."
    if PayerAllocation.query.filter_by(field_id=field.id).first():
        return "Поле використовується в розподілі закупівель. Остаточне видалення заблоковано."

    records = FieldSeason.query.filter_by(field_id=field.id).all()
    if len(records) > 1:
        return "Поле вже має історію в кількох сезонах. Щоб зберегти сівозміну, доступна лише архівація."
    if records and records[0].season.is_closed:
        return "Поле належить до закритого сезону. Його історію не можна видаляти."
    return None



@fields_bp.route("/fields/<int:id>/permanent-delete", methods=["GET", "POST"])
@admin_required
def permanent_delete(id):
    """Allow one authenticated administrator to delete an unused field.

    Hidden links are not security; GET and POST both enforce the admin role.
    Other operational references and historical/closed seasons remain protected.
    """
    field = Field.query.get_or_404(id)
    blocker = _permanent_delete_blocker(field)
    form = ActionForm()

    if request.method == "POST":
        if not form.validate_on_submit():
            abort(400, description="Невірне підтвердження видалення.")
        if blocker:
            flash(blocker, "warning")
            return redirect(url_for("fields.permanent_delete", id=id))

        field_label = field.name
        try:
            for record in FieldSeason.query.filter_by(field_id=id).all():
                db.session.delete(record)
            db.session.flush()
            db.session.delete(field)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                "Поле пов’язане з іншими даними. "
                "Скористайтеся архівацією.", "danger",
            )
            return redirect(url_for("fields.permanent_delete", id=id))
        flash(f"Поле «{field_label}» остаточно видалено.", "success")
        return redirect(url_for("fields.index"))

    return render_template(
        "fields/permanent_delete.html",
        field=field, form=form, blocker=blocker,
        seasonal_count=FieldSeason.query.filter_by(field_id=id).count(),
    )


@fields_bp.post("/fields/<int:id>/delete")
def delete(id):
    if not ActionForm().validate_on_submit():
        abort(400)
    field = Field.query.get_or_404(id)
    field.is_active = False
    db.session.commit()
    flash("Поле переміщено в архів. Сівозміна та плани збережені.", "info")
    return redirect(url_for("fields.index"))


@fields_bp.post("/fields/<int:id>/restore")
def restore(id):
    if not ActionForm().validate_on_submit():
        abort(400)
    field = Field.query.get_or_404(id)
    if _active_duplicate(field.name, field.company_id, exclude_id=id):
        flash("Неможливо відновити поле: існує активне поле з таким номером.", "warning")
    else:
        field.is_active = True
        db.session.commit()
        flash("Поле відновлено.", "success")
    return redirect(url_for("fields.detail", id=id))


@fields_bp.post("/fields/wipe")
def wipe_fields():
    """Disable the old destructive endpoint; protect linked plans and seasons."""
    abort(403, description="Масове видалення застарілим маршрутом вимкнено.")
