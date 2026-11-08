"""Master directory of currencies. Existing symbol codes remain valid."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .models import Currency
from .forms import CurrencyDeleteForm, CurrencyForm


bp = Blueprint("currencies", __name__, url_prefix="/currencies", template_folder="templates")


def _duplicate(code, exclude_id=None):
    query = Currency.query.filter(func.upper(Currency.code) == code.upper())
    if exclude_id is not None:
        query = query.filter(Currency.id != exclude_id)
    return query.first()


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Currency.query
    if search:
        query = query.filter(or_(
            Currency.code.ilike(f"%{search}%"),
            Currency.name.ilike(f"%{search}%"),
        ))
    return render_template(
        "currencies/index.html",
        currencies=query.order_by(Currency.code).all(),
        dependencies=linked_record_counts(Currency),
        delete_form=CurrencyDeleteForm(),
        search=search,
        create_url=url_for("currencies.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CurrencyForm()
    if form.validate_on_submit():
        if _duplicate(form.code.data):
            form.code.errors.append("Валюта з таким кодом або символом уже існує.")
        else:
            try:
                db.session.add(Currency(code=form.code.data, name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.code.errors.append("Не вдалося зберегти валюту: код уже використовується.")
            else:
                flash("Валюту додано.", "success")
                return redirect(url_for("currencies.index"))
    return render_template("currencies/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    currency = Currency.query.get_or_404(id)
    form = CurrencyForm(obj=currency)
    if form.validate_on_submit():
        if _duplicate(form.code.data, exclude_id=currency.id):
            form.code.errors.append("Валюта з таким кодом або символом уже існує.")
        else:
            currency.code = form.code.data
            currency.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.code.errors.append("Не вдалося оновити валюту.")
            else:
                flash("Валюту оновлено.", "success")
                return redirect(url_for("currencies.index"))
    return render_template("currencies/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if not CurrencyDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("currencies.index"))
    currency = Currency.query.get_or_404(id)
    if linked_record_counts(Currency).get(currency.id, 0):
        flash("Валюта використовується в інших модулях. Видалення заблоковано.", "warning")
        return redirect(url_for("currencies.index"))
    try:
        db.session.delete(currency)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Валюта має пов'язані записи й не може бути видалена.", "warning")
    else:
        flash("Валюту видалено.", "info")
    return redirect(url_for("currencies.index"))
