"""Companies as reference records shared by fields, plans and purchasing."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldSeason
from modules.reference.warehouses.models import Warehouse

from .forms import CompanyDeleteForm, CompanyFilterForm, CompanyForm

companies_bp = Blueprint("companies", __name__, template_folder="templates")

# Known foreign-key consumers of companies. Restrict deletion, never cascade.
_DEPENDENCIES = (
    ("полів", Field.company_id),
    ("сезонних записів полів", FieldSeason.company_id),
    ("складів", Warehouse.company_id),
)


def _dependency_counts():
    # Import downstream consumers lazily to avoid initialization cycles while
    # Flask registers the companies and shipping blueprints.
    from modules.purchases.payer_allocation.models import PayerAllocation
    from modules.purchases.payments.models import PaymentInbox
    from modules.requests.shipments.models import ShipmentRequestItem

    refs = _DEPENDENCIES + (
        ("розподілів закупівель", PayerAllocation.company_id),
        ("проплат", PaymentInbox.company_id),
        ("рядків заявок", ShipmentRequestItem.consumer_company_id),
    )
    counts = {}
    for label, column in refs:
        for company_id, amount in (
            db.session.query(column, func.count())
            .filter(column.isnot(None))
            .group_by(column)
            .all()
        ):
            if amount:
                counts.setdefault(company_id, {})[label] = amount
    return counts


def _form_page(form, title, field_count=0):
    return render_template(
        "companies/form.html",
        form=form,
        title=title,
        field_count=field_count,
        has_clusters=bool(Cluster.query.first()),
    )


@companies_bp.route("/companies")
def index():
    form = CompanyFilterForm(request.args)
    query = Company.query.options(joinedload(Company.cluster))

    if form.name.data:
        query = query.filter(Company.id == form.name.data.id)
    if form.cluster.data:
        query = query.filter(Company.cluster_id == form.cluster.data.id)

    companies = query.order_by(Company.name).all()
    return render_template(
        "companies/index.html",
        form=form,
        companies=companies,
        dependencies=_dependency_counts(),
        delete_form=CompanyDeleteForm(),
        create_url=url_for("companies.create"),
    )


@companies_bp.route("/companies/create", methods=["GET", "POST"])
def create():
    form = CompanyForm()
    if form.validate_on_submit():
        company = Company(name=form.name.data, cluster_id=form.cluster.data.id)
        try:
            db.session.add(company)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append("Не вдалося зберегти підприємство: перевірте унікальність і зв'язки.")
        else:
            flash("Підприємство додано.", "success")
            return redirect(url_for("companies.index"))
    return _form_page(form, "Нове підприємство")


@companies_bp.route("/companies/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    company = Company.query.get_or_404(id)
    form = CompanyForm(obj=company, obj_id=company.id)
    field_count = Field.query.filter_by(company_id=company.id).count()
    seasonal_count = FieldSeason.query.filter_by(company_id=company.id).count()

    if form.validate_on_submit():
        if form.cluster.data.id != company.cluster_id and (field_count or seasonal_count):
            # Legacy fields carry both company_id and cluster_id: changing only
            # the company would create contradictory links. Reassign fields first.
            form.cluster.errors.append(
                f"До підприємства прив'язано {field_count} постійних полів "
                f"та {seasonal_count} сезонних записів. "
                "Спочатку перенесіть поля, і лише після цього змінюйте кластер."
            )
        else:
            company.name = form.name.data
            company.cluster_id = form.cluster.data.id
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни: перевірте зв'язки.")
            else:
                flash("Підприємство оновлено.", "success")
                return redirect(url_for("companies.index"))

    return _form_page(form, "Редагувати підприємство", field_count=field_count + seasonal_count)


@companies_bp.route("/companies/delete/<int:id>", methods=["POST"])
def delete(id):
    form = CompanyDeleteForm()
    if not form.validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("companies.index"))

    company = Company.query.get_or_404(id)
    linked = _dependency_counts().get(company.id, {})
    if linked:
        details = ", ".join(f"{label} — {value}" for label, value in linked.items())
        flash(
            f"Підприємство «{company.name}» використовується ({details}). "
            "Спочатку змініть прив'язки; видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("companies.index"))

    try:
        db.session.delete(company)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Підприємство має пов'язані дані й не може бути видалене.", "warning")
    else:
        flash("Підприємство видалено.", "info")
    return redirect(url_for("companies.index"))
