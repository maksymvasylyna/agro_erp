"""Категорії продуктів: safe master-data editing shared with other modules."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import CategoryForm, CategoryDeleteForm
from .models import Category

bp = Blueprint("categories", __name__, url_prefix="/categories", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Category.query.filter(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Category.id != exclude_id)
    return query.first()


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Category.query
    if search:
        query = query.filter(Category.name.ilike(f"%{search}%"))
    return render_template(
        "categories/index.html",
        items=query.order_by(Category.name).all(),
        dependencies=linked_record_counts(Category),
        delete_form=CategoryDeleteForm(),
        search=search,
        create_url=url_for("categories.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CategoryForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            try:
                db.session.add(Category(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: перевірте унікальність.")
            else:
                flash("Додано категорію.", "success")
                return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    category = Category.query.get_or_404(id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=category.id):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            category.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Запис оновлено.", "success")
                return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not CategoryDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("categories.index"))
    category = Category.query.get_or_404(id)
    if linked_record_counts(Category).get(category.id, 0):
        flash("Запис використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("categories.index"))
    try:
        db.session.delete(category)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Запис має залежності та не може бути видалений.", "warning")
    else:
        flash("Запис видалено.", "info")
    return redirect(url_for("categories.index"))
