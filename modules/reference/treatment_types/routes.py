"""Treatment-type directory with stable IDs for existing plans.

The treatments and plan_treatments tables both reference these records.
Never cascade deletion of a referenced treatment type into plans.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.shared_crud import linked_record_counts
from .models import TreatmentType
from .forms import TreatmentTypeForm, TreatmentTypeDeleteForm


treatment_types_bp = Blueprint(
    "treatment_types",
    __name__,
    url_prefix="/reference/treatment_types",
    template_folder="templates",
)


def _duplicate(name, exclude_id=None):
    query = TreatmentType.query.filter(func.lower(TreatmentType.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(TreatmentType.id != exclude_id)
    return query.first()


@treatment_types_bp.route("/")
def index():
    search = (request.args.get("q") or "").strip()
    query = TreatmentType.query
    if search:
        query = query.filter(TreatmentType.name.ilike(f"%{search}%"))
    return render_template(
        "treatment_types/index.html",
        items=query.order_by(TreatmentType.name).all(),
        dependencies=linked_record_counts(TreatmentType),
        delete_form=TreatmentTypeDeleteForm(),
        search=search,
        create_url=url_for("treatment_types.create"),
    )


@treatment_types_bp.route("/create", methods=["GET", "POST"])
def create():
    form = TreatmentTypeForm()
    if form.validate_on_submit():
        if _duplicate(form.name.data):
            form.name.errors.append("Вид обробітку з такою назвою вже існує.")
        else:
            try:
                db.session.add(TreatmentType(name=form.name.data))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти вид обробітку.")
            else:
                flash("Вид обробітку додано. Він доступний під час створення планів.", "success")
                return redirect(url_for("treatment_types.index"))
    return render_template("treatment_types/form.html", form=form, action="Створити")


@treatment_types_bp.route("/edit/<int:item_id>", methods=["GET", "POST"])
def edit(item_id):
    item = TreatmentType.query.get_or_404(item_id)
    form = TreatmentTypeForm(obj=item)
    if form.validate_on_submit():
        if _duplicate(form.name.data, exclude_id=item.id):
            form.name.errors.append("Вид обробітку з такою назвою вже існує.")
        else:
            item.name = form.name.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Вид обробітку оновлено.", "success")
                return redirect(url_for("treatment_types.index"))
    return render_template("treatment_types/form.html", form=form, action="Редагувати")


@treatment_types_bp.route("/delete/<int:item_id>", methods=["POST"])
def delete(item_id):
    if not TreatmentTypeDeleteForm().validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("treatment_types.index"))

    item = TreatmentType.query.get_or_404(item_id)
    used = linked_record_counts(TreatmentType).get(item.id, 0)
    if used:
        flash(
            f"Вид обробітку «{item.name}» використовується у {used} операціях "
            "планів. Видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("treatment_types.index"))

    try:
        db.session.delete(item)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Вид обробітку має пов'язані записи і не може бути видалений.", "warning")
    else:
        flash("Вид обробітку видалено.", "info")
    return redirect(url_for("treatment_types.index"))
