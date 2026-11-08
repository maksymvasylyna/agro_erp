"""Group directory: stable product classification, safe CRUD.

Groups are used by products. Product links must never be orphaned or
implicitly cascaded when the directory is edited.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.products.models import Product
from .forms import GroupDeleteForm, GroupForm
from .models import Group


bp = Blueprint("groups", __name__, url_prefix="/groups", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Group.query.filter(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Group.id != exclude_id)
    return query.first()


def _product_counts():
    return dict(
        db.session.query(Product.group_id, func.count(Product.id))
        .filter(Product.group_id.isnot(None))
        .group_by(Product.group_id)
        .all()
    )


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Group.query
    if search:
        query = query.filter(Group.name.ilike(f"%{search}%"))
    return render_template(
        "groups/index.html",
        groups=query.order_by(Group.name).all(),
        product_counts=_product_counts(),
        delete_form=GroupDeleteForm(),
        search=search,
        create_url=url_for("groups.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = GroupForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Група з такою назвою вже існує.")
        else:
            try:
                db.session.add(Group(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти групу. Перевірте назву.")
            else:
                flash("Групу продуктів додано. Вона доступна при створенні продукту.", "success")
                return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    group = Group.query.get_or_404(id)
    form = GroupForm(obj=group)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=group.id):
            form.name.errors.append("Група з такою назвою вже існує.")
        else:
            group.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни до групи.")
            else:
                flash("Групу продуктів оновлено.", "success")
                return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not GroupDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("groups.index"))

    group = Group.query.get_or_404(id)
    linked = Product.query.filter_by(group_id=group.id).count()
    if linked:
        flash(
            f"Групу «{group.name}» використовують {linked} продуктів. "
            "Спочатку змініть їхню групу; видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("groups.index"))

    try:
        db.session.delete(group)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Група має пов'язані записи та не може бути видалена.", "warning")
    else:
        flash("Групу продуктів видалено.", "info")
    return redirect(url_for("groups.index"))
