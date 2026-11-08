"""Виробники: safe master-data editing shared with other modules."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import ManufacturerForm, ManufacturerDeleteForm
from .models import Manufacturer

bp = Blueprint("manufacturers", __name__, url_prefix="/manufacturers", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Manufacturer.query.filter(func.lower(Manufacturer.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Manufacturer.id != exclude_id)
    return query.first()


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Manufacturer.query
    if search:
        query = query.filter(Manufacturer.name.ilike(f"%{search}%"))
    return render_template(
        "manufacturers/index.html",
        items=query.order_by(Manufacturer.name).all(),
        dependencies=linked_record_counts(Manufacturer),
        delete_form=ManufacturerDeleteForm(),
        search=search,
        create_url=url_for("manufacturers.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = ManufacturerForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            try:
                db.session.add(Manufacturer(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: перевірте унікальність.")
            else:
                flash("Додано виробника.", "success")
                return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    manufacturer = Manufacturer.query.get_or_404(id)
    form = ManufacturerForm(obj=manufacturer)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=manufacturer.id):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            manufacturer.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Запис оновлено.", "success")
                return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not ManufacturerDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("manufacturers.index"))
    manufacturer = Manufacturer.query.get_or_404(id)
    if linked_record_counts(Manufacturer).get(manufacturer.id, 0):
        flash("Запис використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("manufacturers.index"))
    try:
        db.session.delete(manufacturer)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Запис має залежності та не може бути видалений.", "warning")
    else:
        flash("Запис видалено.", "info")
    return redirect(url_for("manufacturers.index"))
