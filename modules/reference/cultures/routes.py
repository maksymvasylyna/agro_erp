from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Culture
from .forms import CultureForm

bp = Blueprint("cultures", __name__, url_prefix="/cultures", template_folder="templates")

@bp.route("/")
def index():
    cultures = Culture.query.all()
    return render_template(
        "cultures/index.html",
        cultures=cultures,
        create_url=url_for("cultures.create")  # ✅ Додаємо!
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CultureForm()
    if form.validate_on_submit():
        new_culture = Culture(name=form.name.data)
        db.session.add(new_culture)
        db.session.commit()
        flash("Культуру додано", "success")
        return redirect(url_for("cultures.index"))
    return render_template("cultures/form.html", form=form, action="Створити")

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    culture = Culture.query.get_or_404(id)
    form = CultureForm(obj=culture)
    if form.validate_on_submit():
        culture.name = form.name.data
        db.session.commit()
        flash("Культуру оновлено", "success")
        return redirect(url_for("cultures.index"))
    return render_template("cultures/form.html", form=form, action="Редагувати")

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    culture = Culture.query.get_or_404(id)
    db.session.delete(culture)
    db.session.commit()
    flash("Культуру видалено", "info")
    return redirect(url_for("cultures.index"))