# modules/reference/payers/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Payer
from .forms import PayerForm

bp = Blueprint("payers", __name__, url_prefix="/payers", template_folder="templates")

@bp.route("/")
def index():
    payers = Payer.query.order_by(Payer.name).all()
    return render_template(
        "payers/index.html",
        payers=payers,
        create_url=url_for("payers.create")  # ✅ Ось ключове!
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = PayerForm()
    if form.validate_on_submit():
        new_payer = Payer(name=form.name.data)
        db.session.add(new_payer)
        db.session.commit()
        flash("Платника додано", "success")
        return redirect(url_for("payers.index"))
    return render_template("payers/form.html", form=form, action="Створити")

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    payer = Payer.query.get_or_404(id)
    form = PayerForm(obj=payer)
    if form.validate_on_submit():
        payer.name = form.name.data
        db.session.commit()
        flash("Платника оновлено", "success")
        return redirect(url_for("payers.index"))
    return render_template("payers/form.html", form=form, action="Редагувати")

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    payer = Payer.query.get_or_404(id)
    db.session.delete(payer)
    db.session.commit()
    flash("Платника видалено", "info")
    return redirect(url_for("payers.index"))
