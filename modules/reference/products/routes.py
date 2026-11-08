"""Products are canonical master records used by plans and purchasing.

Existing product IDs and all related operational data remain intact.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import ProductDeleteForm, ProductFilterForm, ProductForm
from .models import Product


products_bp = Blueprint("products", __name__, template_folder="templates")


def _identity(name, manufacturer_id, category_id, container):
    """Define a product variant without merging unrelated manufacturers or packages."""
    return (
        (name or "").strip().casefold(),
        manufacturer_id,
        category_id,
        (container or "").strip().casefold(),
    )


def _duplicate(form, exclude_id=None):
    """Detect a same-name, same-manufacturer, same-category and same-package item."""
    query = Product.query.filter(
        func.lower(Product.name) == form.name.data.lower(),
        Product.manufacturer_id == form.manufacturer.data.id,
        Product.category_id == form.category.data.id,
        func.lower(func.coalesce(Product.container, "")) ==
        (form.container.data or "").lower(),
    )
    if exclude_id is not None:
        query = query.filter(Product.id != exclude_id)
    return query.first()


def _apply_values(product, form):
    product.name = form.name.data
    product.category_id = form.category.data.id
    product.group_id = form.group.data.id
    product.manufacturer_id = form.manufacturer.data.id
    product.unit_id = form.unit.data.id
    product.container = form.container.data or None


@products_bp.route("/products")
def index():
    form = ProductFilterForm(request.args)
    query = Product.query.options(
        joinedload(Product.category),
        joinedload(Product.group),
        joinedload(Product.manufacturer),
        joinedload(Product.unit),
    )
    search = (request.args.get("q") or "").strip()
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if form.category.data:
        query = query.filter(Product.category_id == form.category.data.id)
    if form.group.data:
        query = query.filter(Product.group_id == form.group.data.id)
    if form.manufacturer.data:
        query = query.filter(Product.manufacturer_id == form.manufacturer.data.id)

    return render_template(
        "products/index.html",
        items=query.order_by(Product.name, Product.id).all(),
        form=form,
        search=search,
        dependencies=linked_record_counts(Product),
        delete_form=ProductDeleteForm(),
        create_url=url_for("products.create"),
    )


@products_bp.route("/products/create", methods=["GET", "POST"])
def create():
    form = ProductForm()
    if form.validate_on_submit():
        if _duplicate(form):
            form.name.errors.append(
                "Продукт із такою назвою, категорією, виробником і тарою вже існує."
            )
        else:
            product = Product()
            _apply_values(product, form)
            try:
                db.session.add(product)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти продукт. Перевірте зв'язки.")
            else:
                flash("Продукт додано. Він доступний у виборі препаратів для планів.", "success")
                return redirect(url_for("products.index"))
    return render_template("products/form.html", form=form, action="Створити")


@products_bp.route("/products/<int:id>/edit", methods=["GET", "POST"])
def edit(id):
    product = Product.query.get_or_404(id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        current_identity = _identity(
            product.name, product.manufacturer_id,
            product.category_id, product.container,
        )
        proposed_identity = _identity(
            form.name.data, form.manufacturer.data.id,
            form.category.data.id, form.container.data,
        )
        # Two existing records can share an identity. Editing other fields
        # must remain possible without forcing a destructive legacy merge.
        if current_identity != proposed_identity and _duplicate(form, exclude_id=id):
            form.name.errors.append(
                "Продукт із такою назвою, категорією, виробником і тарою вже існує."
            )
        else:
            _apply_values(product, form)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни до продукту.")
            else:
                flash("Продукт оновлено.", "success")
                return redirect(url_for("products.index"))
    return render_template("products/form.html", form=form, action="Редагувати")


@products_bp.route("/products/<int:id>/delete", methods=["POST"])
def delete(id):
    if not ProductDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("products.index"))

    product = Product.query.get_or_404(id)
    if linked_record_counts(Product).get(product.id, 0):
        flash(
            "Продукт використовується в планах, закупівлях, заявках або "
            "складських операціях. Видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("products.index"))

    try:
        db.session.delete(product)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Продукт має пов'язані записи й не може бути видалений.", "warning")
    else:
        flash("Продукт видалено.", "info")
    return redirect(url_for("products.index"))
