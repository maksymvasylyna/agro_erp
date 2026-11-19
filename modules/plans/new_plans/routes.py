"""New technological plans: all selections and writes belong to the current season."""
from decimal import Decimal
from sqlalchemy import func

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from extensions import db
from modules.plans.models import Plan, Treatment
from modules.plans.security import prepare_treatments
from modules.plans.new_plans.forms import PlanForm
from modules.plans.season import context, current, validate_posted_season, writable
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldPlanting, FieldSeason
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType

bp = Blueprint("new_plans", __name__, url_prefix="/new_plans",
               template_folder="templates")


def _eligible_rows(season):
    used = db.session.query(Plan.field_id).filter(Plan.season_id == season.id)
    single_crop = (db.session.query(FieldPlanting.field_season_id)
                   .group_by(FieldPlanting.field_season_id)
                   .having(func.count(FieldPlanting.id) == 1))
    return (
        FieldSeason.query.join(Field, FieldSeason.field_id == Field.id)
        .options(
            joinedload(FieldSeason.field),
            joinedload(FieldSeason.company),
            joinedload(FieldSeason.cluster),
            joinedload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        )
        .filter(FieldSeason.season_id == season.id,
                FieldSeason.id.in_(single_crop),
                ~FieldSeason.field_id.in_(used))
    )


def _populate_choices(form, treatment_types, products):
    for subform in form.treatments:
        subform.treatment_type_id.choices = [(t.id, t.name) for t in treatment_types]
        subform.product_id.choices = [(p.id, p.name) for p in products]


def _choices():
    return (
        TreatmentType.query.order_by(TreatmentType.name).all(),
        Product.query.options(
            joinedload(Product.manufacturer), joinedload(Product.unit)
        ).filter(Product.is_archived.is_(False)).order_by(Product.name).all(),
    )


def _season_labels(rows):
    """Always display current-year attributes, never the legacy field snapshot."""
    return {
        row.field_id: {
            "area": row.area,
            "culture": ", ".join(
                sorted({p.culture.name for p in row.plantings})
            ) or "—",
            "company": row.company.name,
        }
        for row in rows
    }


@bp.get("/")
def index():
    return render_template("new_plans/index.html", **context())


@bp.get("/select_cluster")
def select_cluster():
    season = current()
    cluster_ids = {
        r[0] for r in db.session.query(FieldSeason.cluster_id)
        .filter(FieldSeason.season_id == season.id).distinct()
    }
    clusters = Cluster.query.filter(Cluster.id.in_(cluster_ids)).order_by(Cluster.name).all()
    return render_template("new_plans/select_cluster.html", clusters=clusters,
                           **context())


@bp.get("/select_company/<int:cluster_id>")
def select_company(cluster_id):
    season = current()
    company_ids = {
        r[0] for r in db.session.query(FieldSeason.company_id)
        .filter(FieldSeason.season_id == season.id,
                FieldSeason.cluster_id == cluster_id).distinct()
    }
    companies = Company.query.filter(Company.id.in_(company_ids)).order_by(Company.name).all()
    return render_template("new_plans/select_company.html", companies=companies,
                           cluster_id=cluster_id, **context())


@bp.get("/select_field/<int:cluster_id>/<int:company_id>")
def select_field(cluster_id, company_id):
    season = current()
    company = Company.query.get_or_404(company_id)
    rows = (
        _eligible_rows(season)
        .filter(FieldSeason.cluster_id == cluster_id,
                FieldSeason.company_id == company_id)
        .order_by(Field.name).all()
    )
    return render_template(
        "new_plans/select_field.html", company=company, cluster_id=cluster_id,
        fields=[r.field for r in rows], season_labels=_season_labels(rows),
        **context(),
    )


@bp.route("/create/<int:field_id>", methods=["GET", "POST"])
def create_plan(field_id):
    season = writable() if request.method == "POST" else current()
    field = Field.query.get_or_404(field_id)
    record_query = FieldSeason.query.filter_by(field_id=field_id, season_id=season.id)
    # On PostgreSQL hold the seasonal field row until the plan is committed:
    # concurrent requests cannot both pass the duplicate check.
    record = (record_query.with_for_update() if request.method == "POST"
              else record_query).first_or_404()
    if len(record.plantings) != 1:
        abort(409, description="Поле повинно мати рівно одну культуру в структурі посівів.")
    if Plan.query.filter_by(field_id=field_id, season_id=season.id).first():
        flash("Для цього поля вже створено план у вибраному сезоні.", "warning")
        return redirect(url_for("new_plans.select_field",
                                cluster_id=record.cluster_id,
                                company_id=record.company_id))
    form = PlanForm()
    treatment_types, products = _choices()
    _populate_choices(form, treatment_types, products)
    if request.method == "POST":
        validate_posted_season(season)
        if form.validate_on_submit():
            lines = prepare_treatments(form, record.area)
            plan = Plan(field_id=field.id, season_id=season.id)
            db.session.add(plan)
            db.session.flush()
            for line in lines:
                line.plan_id = plan.id
                db.session.add(line)
            db.session.commit()
            flash(f"План збережено для сезону {season.year}.", "success")
            return redirect(url_for("new_plans.index"))
        flash("Форма не пройшла перевірку.", "danger")
    return render_template(
        "new_plans/create_plan.html", form=form, field=field,
        season_field=record, culture_label=_season_labels([record])[field_id]["culture"],
        cluster_id=record.cluster_id, cluster=record.cluster,
        company=record.company,
        treatment_types=treatment_types, products=products, **context(),
    )


@bp.route("/bulk_template/select_fields", methods=["GET", "POST"])
def bulk_template_select_fields():
    season = writable() if request.method == "POST" else current()
    selected_company_id = request.args.get("company_id", type=int)
    selected_culture_id = request.args.get("culture_id", type=int)
    query = _eligible_rows(season)
    if selected_company_id is not None:
        query = query.filter(FieldSeason.company_id == selected_company_id)
    if selected_culture_id is not None:
        query = query.filter(
            FieldSeason.plantings.any(FieldPlanting.culture_id == selected_culture_id)
        )
    rows = query.order_by(Field.name).all()
    if request.method == "POST":
        validate_posted_season(season)
        requested = request.form.getlist("field_ids")
        ids = {str(r.field_id) for r in rows}
        if not requested:
            flash("Оберіть хоча б одне поле.", "warning")
            return redirect(request.url)
        if any(v not in ids for v in requested):
            abort(400, description="Обрано поле, яке не належить до сезону чи фільтрів.")
        return redirect(url_for(
            "new_plans.bulk_template_create", field_ids=",".join(requested)
        ))
    return render_template(
        "new_plans/bulk_template/select_fields.html",
        fields=[r.field for r in rows], season_labels=_season_labels(rows),
        companies=Company.query.order_by(Company.name).all(),
        cultures=Culture.query.order_by(Culture.name).all(),
        selected_company_id=selected_company_id,
        selected_culture_id=selected_culture_id, **context(),
    )


@bp.route("/bulk_template/create", methods=["GET", "POST"])
def bulk_template_create():
    season = writable() if request.method == "POST" else current()
    raw = request.args.get("field_ids") or request.form.get("field_ids")
    if not raw:
        return redirect(url_for("new_plans.bulk_template_select_fields"))
    try:
        ids = list(dict.fromkeys(int(p) for p in raw.split(",")))
    except ValueError:
        abort(400)
    if not ids or len(ids) > 1000 or any(i < 1 for i in ids):
        abort(400)
    if request.method == "POST":
        validate_posted_season(season)
        # Lock every selected field in deterministic order before rechecking
        # its eligibility, including concurrent single-plan submissions.
        (db.session.query(FieldSeason.id)
         .filter(FieldSeason.season_id == season.id,
                 FieldSeason.field_id.in_(ids))
         .order_by(FieldSeason.id).with_for_update().all())
    rows = _eligible_rows(season).filter(FieldSeason.field_id.in_(ids)).all()
    if {r.field_id for r in rows} != set(ids):
        abort(400, description="Деякі поля відсутні у вибраному сезоні або вже мають план.")
    mapping = {r.field_id: r for r in rows}
    fields = [mapping[i].field for i in ids]
    labels = _season_labels(rows)
    form = PlanForm()
    treatment_types, products = _choices()
    _populate_choices(form, treatment_types, products)
    if request.method == "POST":
        validate_posted_season(season)
        if form.validate_on_submit():
            for field in fields:
                lines = prepare_treatments(form, mapping[field.id].area)
                plan = Plan(field_id=field.id, season_id=season.id)
                db.session.add(plan)
                db.session.flush()
                for line in lines:
                    line.plan_id = plan.id
                    db.session.add(line)
            db.session.commit()
            flash(f"Створено {len(fields)} планів для сезону {season.year}.", "success")
            return redirect(url_for("new_plans.index"))
        flash("Форма не пройшла перевірку.", "danger")
    return render_template(
        "new_plans/bulk_template/template_form.html", form=form,
        fields=fields, season_labels=labels, treatment_types=treatment_types,
        products=products, field_ids=",".join(map(str, ids)),
        total_area=sum((r.area for r in rows), Decimal("0.00")),
        **context(),
    )


new_plans_bp = bp
