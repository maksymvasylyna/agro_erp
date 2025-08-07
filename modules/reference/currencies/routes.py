# modules/reference/currencies/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Currency
from .forms import CurrencyForm

bp = Blueprint("currencies", __name__, url_prefix="/currencies", template_folder="templates")

@bp.route("/")
def index():
    currencies = Currency.query.all()
    return render_template(
        "currencies/index.html",
        currencies=currencies,
        create_url=url_for("currencies.create")  # ✅ ключове!
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CurrencyForm()
    if form.validate_on_submit():
        currency = Currency(code=form.code.data.upper(), name=form.name.data)
        db.session.add(currency)
        db.session.commit()
        flash("Валюту додано", "success")
        return redirect(url_for("currencies.index"))
    return render_template("currencies/form.html", form=form)

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    currency = Currency.query.get_or_404(id)
    form = CurrencyForm(obj=currency)
    if form.validate_on_submit():
        currency.code = form.code.data.upper()
        currency.name = form.name.data
        db.session.commit()
        flash("Валюту оновлено", "success")
        return redirect(url_for("currencies.index"))
    return render_template("currencies/form.html", form=form)

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    currency = Currency.query.get_or_404(id)
    db.session.delete(currency)
    db.session.commit()
    flash("Валюту видалено", "info")
    return redirect(url_for("currencies.index"))
