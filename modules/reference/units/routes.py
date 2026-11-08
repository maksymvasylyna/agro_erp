"""Одиниці виміру: safe master-data editing shared with other modules."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import UnitForm, UnitDeleteForm
from .models import Unit

bp = Blueprint("units", __name__, template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Unit.query.filter(func.lower(Unit.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Unit.id != exclude_id)
    return query.first()


@bp.route("/units")
def index():
    search = (request.args.get("q") or "").strip()
    query = Unit.query
    if search:
        query = query.filter(Unit.name.ilike(f"%{search}%"))
    return render_template(
        "units/index.html",
        items=query.order_by(Unit.name).all(),
        dependencies=linked_record_counts(Unit),
        delete_form=UnitDeleteForm(),
        search=search,
        create_url=url_for("units.create"),
    )


@bp.route("/units/create", methods=["GET", "POST"])
def create():
    form = UnitForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            try:
                db.session.add(Unit(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: перевірте унікальність.")
            else:
                flash("Додано одиницю виміру.", "success")
                return redirect(url_for("units.index"))
    return render_template("units/form.html", form=form, action="Створити")


@bp.route("/units/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    unit = Unit.query.get_or_404(id)
    form = UnitForm(obj=unit)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=unit.id):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            unit.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Запис оновлено.", "success")
                return redirect(url_for("units.index"))
    return render_template("units/form.html", form=form, action="Редагувати")


@bp.route("/units/delete/<int:id>", methods=["POST"])
def delete(id):
    if not UnitDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("units.index"))
    unit = Unit.query.get_or_404(id)
    if linked_record_counts(Unit).get(unit.id, 0):
        flash("Запис використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("units.index"))
    try:
        db.session.delete(unit)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Запис має залежності та не може бути видалений.", "warning")
    else:
        flash("Запис видалено.", "info")
    return redirect(url_for("units.index"))
