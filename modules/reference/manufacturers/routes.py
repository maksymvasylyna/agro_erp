# modules/reference/manufacturers/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Manufacturer
from .forms import ManufacturerForm

bp = Blueprint("manufacturers", __name__, url_prefix="/manufacturers", template_folder="templates")

@bp.route("/")
def index():
    manufacturers = Manufacturer.query.order_by(Manufacturer.name).all()
    return render_template(
        "manufacturers/index.html",
        manufacturers=manufacturers,
        create_url=url_for("manufacturers.create")  # ✅ Ключове!
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = ManufacturerForm()
    if form.validate_on_submit():
        new_manufacturer = Manufacturer(name=form.name.data)
        db.session.add(new_manufacturer)
        db.session.commit()
        flash("Виробника додано", "success")
        return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Створити")

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    manufacturer = Manufacturer.query.get_or_404(id)
    form = ManufacturerForm(obj=manufacturer)
    if form.validate_on_submit():
        manufacturer.name = form.name.data
        db.session.commit()
        flash("Виробника оновлено", "success")
        return redirect(url_for("manufacturers.index"))
    return render_template("manufacturers/form.html", form=form, action="Редагувати")

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    manufacturer = Manufacturer.query.get_or_404(id)
    db.session.delete(manufacturer)
    db.session.commit()
    flash("Виробника видалено", "info")
    return redirect(url_for("manufacturers.index"))
