"""Manufacturer directory used by products, purchasing and shipments.

Manufacturer IDs remain stable; deleting linked manufacturers is prohibited.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.products.models import Product
from modules.reference.shared_crud import linked_record_counts
from .forms import ManufacturerDeleteForm, ManufacturerForm
from .models import Manufacturer


bp = Blueprint("manufacturers", __name__, url_prefix="/manufacturers", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Manufacturer.query.filter(func.lower(Manufacturer.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Manufacturer.id != exclude_id)
    return query.first()


def _product_counts():
    return dict(
        db.session.query(Product.manufacturer_id, func.count(Product.id))
        .filter(Product.manufacturer_id.isnot(None))
        .group_by(Product.manufacturer_id)
        .all()
    )


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Manufacturer.query
    if search:
        query = query.filter(Manufacturer.name.ilike(f"%{search}%"))
    return render_template(
        "manufacturers/index.html",
        manufacturers=query.order_by(Manufacturer.name).all(),
        product_counts=_product_counts(),
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
            form.name.errors.append("Виробник із такою назвою вже існує.")
        else:
            try:
                db.session.add(Manufacturer(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти виробника: перевірте назву.")
            else:
                flash("Виробника додано. Він доступний у довіднику продуктів.", "success")
                return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    manufacturer = Manufacturer.query.get_or_404(id)
    form = ManufacturerForm(obj=manufacturer)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=manufacturer.id):
            form.name.errors.append("Виробник із такою назвою вже існує.")
        else:
            manufacturer.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни до виробника.")
            else:
                flash("Виробника оновлено.", "success")
                return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not ManufacturerDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("manufacturers.index"))

    manufacturer = Manufacturer.query.get_or_404(id)
    linked = linked_record_counts(Manufacturer).get(manufacturer.id, 0)
    if linked:
        flash(
            f"Виробник «{manufacturer.name}» має {linked} пов'язаних записів "
            "у продуктах, закупівлях або заявках. Видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("manufacturers.index"))

    try:
        db.session.delete(manufacturer)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Виробник використовується іншими даними та не може бути видалений.", "warning")
    else:
        flash("Виробника видалено.", "info")
    return redirect(url_for("manufacturers.index"))
