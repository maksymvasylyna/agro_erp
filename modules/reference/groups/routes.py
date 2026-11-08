"""Групи продуктів: safe master-data editing shared with other modules."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import GroupForm, GroupDeleteForm
from .models import Group

bp = Blueprint("groups", __name__, url_prefix="/groups", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Group.query.filter(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Group.id != exclude_id)
    return query.first()


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Group.query
    if search:
        query = query.filter(Group.name.ilike(f"%{search}%"))
    return render_template(
        "groups/index.html",
        items=query.order_by(Group.name).all(),
        dependencies=linked_record_counts(Group),
        delete_form=GroupDeleteForm(),
        search=search,
        create_url=url_for("groups.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = GroupForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            try:
                db.session.add(Group(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: перевірте унікальність.")
            else:
                flash("Додано групу.", "success")
                return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    group = Group.query.get_or_404(id)
    form = GroupForm(obj=group)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=group.id):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            group.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Запис оновлено.", "success")
                return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not GroupDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("groups.index"))
    group = Group.query.get_or_404(id)
    if linked_record_counts(Group).get(group.id, 0):
        flash("Запис використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("groups.index"))
    try:
        db.session.delete(group)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Запис має залежності та не може бути видалений.", "warning")
    else:
        flash("Запис видалено.", "info")
    return redirect(url_for("groups.index"))
