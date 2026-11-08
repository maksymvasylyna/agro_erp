"""Платники: safe master-data editing shared with other modules."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .forms import PayerForm, PayerDeleteForm
from .models import Payer

bp = Blueprint("payers", __name__, url_prefix="/payers", template_folder="templates")


def _duplicate(name, exclude_id=None):
    query = Payer.query.filter(func.lower(Payer.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Payer.id != exclude_id)
    return query.first()


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Payer.query
    if search:
        query = query.filter(Payer.name.ilike(f"%{search}%"))
    return render_template(
        "payers/index.html",
        items=query.order_by(Payer.name).all(),
        dependencies=linked_record_counts(Payer),
        delete_form=PayerDeleteForm(),
        search=search,
        create_url=url_for("payers.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = PayerForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            try:
                db.session.add(Payer(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: перевірте унікальність.")
            else:
                flash("Додано платника.", "success")
                return redirect(url_for("payers.index"))
    return render_template("payers/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    payer = Payer.query.get_or_404(id)
    form = PayerForm(obj=payer)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=payer.id):
            form.name.errors.append("Запис із такою назвою вже існує.")
        else:
            payer.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Запис оновлено.", "success")
                return redirect(url_for("payers.index"))
    return render_template("payers/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not PayerDeleteForm().validate_on_submit():
        flash("Невірне підтвердження видалення.", "warning")
        return redirect(url_for("payers.index"))
    payer = Payer.query.get_or_404(id)
    if linked_record_counts(Payer).get(payer.id, 0):
        flash("Запис використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("payers.index"))
    try:
        db.session.delete(payer)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Запис має залежності та не може бути видалений.", "warning")
    else:
        flash("Запис видалено.", "info")
    return redirect(url_for("payers.index"))
