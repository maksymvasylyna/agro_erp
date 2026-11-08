"""Reference directory for product categories.

Category IDs are shared with products. Never cascade category deletion into
products, plans, purchasing or operational records.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.products.models import Product
from .forms import CategoryDeleteForm, CategoryForm
from .models import Category


bp = Blueprint(
    "categories", __name__,
    url_prefix="/categories", template_folder="templates",
)


def _duplicate(name, exclude_id=None):
    query = Category.query.filter(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Category.id != exclude_id)
    return query.first()


def _product_counts():
    return dict(
        db.session.query(Product.category_id, func.count(Product.id))
        .filter(Product.category_id.isnot(None))
        .group_by(Product.category_id)
        .all()
    )


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Category.query
    if search:
        query = query.filter(Category.name.ilike(f"%{search}%"))

    return render_template(
        "categories/index.html",
        categories=query.order_by(Category.name).all(),
        product_counts=_product_counts(),
        delete_form=CategoryDeleteForm(),
        search=search,
        create_url=url_for("categories.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CategoryForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Категорія з такою назвою вже існує.")
        else:
            try:
                db.session.add(Category(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти категорію. Перевірте назву.")
            else:
                flash("Категорію додано.", "success")
                return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    category = Category.query.get_or_404(id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=category.id):
            form.name.errors.append("Категорія з такою назвою вже існує.")
        else:
            category.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося оновити категорію.")
            else:
                flash("Категорію оновлено.", "success")
                return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not CategoryDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("categories.index"))

    category = Category.query.get_or_404(id)
    product_count = Product.query.filter_by(category_id=category.id).count()
    if product_count:
        flash(
            f"Категорію «{category.name}» використовують {product_count} продуктів. "
            "Спочатку змініть їхню категорію; видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("categories.index"))

    try:
        db.session.delete(category)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Категорія має пов'язані записи та не може бути видалена.", "warning")
    else:
        flash("Категорію видалено.", "info")
    return redirect(url_for("categories.index"))
