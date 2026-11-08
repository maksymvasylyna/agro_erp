"""Product directory shared by plans, purchasing, warehouse and shipments."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import ProductDeleteForm, ProductForm, ProductFilterForm
from .models import Product

products_bp = Blueprint("products", __name__, template_folder="templates")


def _signature(name, manufacturer_id, category_id, container):
    return (
        (name or "").casefold(),
        manufacturer_id,
        category_id,
        (container or "").casefold(),
    )


def _duplicate(form, excluded_id=None):
    """Allow the same product name in distinct manufacturers, categories or packages."""
    query = Product.query.filter(
        func.lower(Product.name) == form.name.data.lower(),
        Product.manufacturer_id == form.manufacturer.data.id,
        Product.category_id == form.category.data.id,
        func.lower(func.coalesce(Product.container, "")) == (form.container.data or "").lower(),
    )
    if excluded_id is not None:
        query = query.filter(Product.id != excluded_id)
    return query.first()


def _apply_fields(product, form):
    product.name = form.name.data
    product.category_id = form.category.data.id
    product.group_id = form.group.data.id
    product.unit_id = form.unit.data.id
    product.manufacturer_id = form.manufacturer.data.id
    product.container = form.container.data or None


@products_bp.route("/products")
def index():
    form = ProductFilterForm(request.args)
    query = Product.query.options(
        joinedload(Product.category), joinedload(Product.group),
        joinedload(Product.unit), joinedload(Product.manufacturer),
    )
    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    if form.category.data:
        query = query.filter(Product.category_id == form.category.data.id)
    if form.group.data:
        query = query.filter(Product.group_id == form.group.data.id)
    if form.manufacturer.data:
        query = query.filter(Product.manufacturer_id == form.manufacturer.data.id)
    return render_template(
        "products/index.html",
        items=query.order_by(Product.name).all(),
        form=form, search=q,
        dependencies=linked_record_counts(Product),
        delete_form=ProductDeleteForm(),
        create_url=url_for("products.create"),
    )


@products_bp.route("/products/create", methods=["GET", "POST"])
def create():
    form = ProductForm()
    if form.validate_on_submit():
        if _duplicate(form):
            form.name.errors.append("Такий продукт із цією тарою вже існує у вибраного виробника й категорії.")
        else:
            product = Product()
            _apply_fields(product, form)
            try:
                db.session.add(product)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти продукт: перевірте зв'язки.")
            else:
                flash("Продукт додано. Він доступний для вибору в планах.", "success")
                return redirect(url_for("products.index"))
    return render_template("products/form.html", form=form, action="Створити")


@products_bp.route("/products/<int:id>/edit", methods=["GET", "POST"])
def edit(id):
    product = Product.query.get_or_404(id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        previous = _signature(
            product.name, product.manufacturer_id,
            product.category_id, product.container,
        )
        proposed = _signature(
            form.name.data, form.manufacturer.data.id,
            form.category.data.id, form.container.data,
        )
        # Legacy database has a few exact duplicates; editing other attributes
        # must not require changing those historic identifiers.
        if previous != proposed and _duplicate(form, excluded_id=product.id):
            form.name.errors.append("Такий продукт уже є в цій категорії, у виробника та з такою тарою.")
        else:
            _apply_fields(product, form)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося оновити продукт.")
            else:
                flash("Продукт оновлено.", "success")
                return redirect(url_for("products.index"))
    return render_template("products/form.html", form=form, action="Редагувати")


@products_bp.route("/products/<int:id>/delete", methods=["POST"])
def delete(id):
    if not ProductDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("products.index"))
    product = Product.query.get_or_404(id)
    if linked_record_counts(Product).get(product.id, 0):
        flash("Продукт використовується в планах, закупівлях або інших операціях. Видалення заблоковано.", "warning")
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
