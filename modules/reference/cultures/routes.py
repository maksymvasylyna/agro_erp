"""Crop/culture reference data shared by field rotations and plans."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.fields.field_models import Field
from .forms import CultureDeleteForm, CultureForm
from .models import Culture

bp = Blueprint("cultures", __name__, url_prefix="/cultures", template_folder="templates")


def _field_counts():
    return dict(
        db.session.query(Field.culture_id, func.count(Field.id))
        .filter(Field.culture_id.isnot(None))
        .group_by(Field.culture_id)
        .all()
    )


@bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = Culture.query
    if search:
        query = query.filter(Culture.name.ilike(f"%{search}%"))
    return render_template(
        "cultures/index.html",
        cultures=query.order_by(Culture.name).all(),
        field_counts=_field_counts(),
        delete_form=CultureDeleteForm(),
        create_url=url_for("cultures.create"),
        search=search,
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CultureForm()
    if form.validate_on_submit():
        try:
            db.session.add(Culture(name=form.name.data))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append("Не вдалося додати культуру: перевірте зв'язки та унікальність.")
        else:
            flash("Культуру додано. Вона доступна для вибору в довіднику полів.", "success")
            return redirect(url_for("cultures.index"))
    return render_template("cultures/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    culture = Culture.query.get_or_404(id)
    form = CultureForm(obj=culture, culture_id=culture.id)
    if form.validate_on_submit():
        culture.name = form.name.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append("Не вдалося зберегти зміни до культури.")
        else:
            flash("Культуру оновлено.", "success")
            return redirect(url_for("cultures.index"))
    return render_template("cultures/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    form = CultureDeleteForm()
    if not form.validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("cultures.index"))

    culture = Culture.query.get_or_404(id)
    fields = Field.query.filter_by(culture_id=culture.id).count()
    if fields:
        flash(
            f"Культуру «{culture.name}» використовують {fields} полів. "
            "Спочатку змініть відповідні записи; видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("cultures.index"))

    # An additional FK in a future seasonal table will also prevent deletion:
    # never cascade to historical rotations or operational records.
    try:
        db.session.delete(culture)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Культура використовується іншими даними й не може бути видалена.", "warning")
    else:
        flash("Культуру видалено.", "info")
    return redirect(url_for("cultures.index"))
