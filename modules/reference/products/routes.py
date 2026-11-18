"""Products are canonical master records used by plans and purchasing.

Existing product IDs and all related operational data remain intact.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import ProductDeleteForm, ProductFilterForm, ProductForm
from .models import Product, ProductIngredient
from .catalog_import import sync_components


products_bp = Blueprint("products", __name__, template_folder="templates")


def _operational_dependency_counts():
    # Ingredients are owned by Product and cascade with it; exclude these
    # internal metadata rows from the operational deletion safeguard.
    counts = linked_record_counts(Product)
    internal = dict(
        db.session.query(ProductIngredient.product_id, func.count())
        .group_by(ProductIngredient.product_id).all()
    )
    return {product_id: max(0, count - internal.get(product_id, 0))
            for product_id, count in counts.items()}


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
    product.formulation_code = form.formulation_code.data or None
    product.formulation_name = form.formulation_name.data or None
    product.composition = form.composition.data or None


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
    # JS gets the full selected archive tab to filter instantly, without
    # refetching. Preserve server-side GET filtering for no-JS users only.
    server_filter = request.args.get("server_filter") == "1"
    if server_filter and search:
        query = query.filter(or_(
            Product.name.ilike(f"%{search}%"),
            Product.composition.ilike(f"%{search}%"),
        ))
    archived = (request.args.get("archived") or "active").strip()
    if archived == "archived":
        query = query.filter(Product.is_archived.is_(True))
    elif archived != "all":
        archived = "active"
        query = query.filter(Product.is_archived.is_(False))
    if server_filter:
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
        dependencies=_operational_dependency_counts(),
        archived=archived,
        active_count=Product.query.filter(Product.is_archived.is_(False)).count(),
        archive_count=Product.query.filter(Product.is_archived.is_(True)).count(),
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
                db.session.flush()
                sync_components(product, product.composition)
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
                sync_components(product, product.composition)
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
    if _operational_dependency_counts().get(product.id, 0):
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
