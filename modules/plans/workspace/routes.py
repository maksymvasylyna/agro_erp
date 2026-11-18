"""Seasonal technology planning: one field, one crop, one plan per season."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from sqlalchemy.orm import joinedload

from admin_auth import is_admin
from extensions import db
from modules.plans.season import context, current, validate_posted_season, writable
from modules.plans.models import Plan
from modules.plans.workspace.models import TechnologyPlan, TechnologyOperation, TechnologyProduct
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldPlanting, FieldSeason
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType

bp = Blueprint("planning_workspace", __name__, url_prefix="/plans/workspace",
               template_folder="templates")
_QTY = Decimal("0.001")


class ActionForm(FlaskForm):
    """Supplies Flask-WTF CSRF validation for dynamically generated rows."""
    pass


def _planting(planting_id, season):
    planting = (
        FieldPlanting.query.options(
            joinedload(FieldPlanting.culture),
            joinedload(FieldPlanting.field_season).joinedload(FieldSeason.field),
            joinedload(FieldPlanting.field_season).joinedload(FieldSeason.company),
            joinedload(FieldPlanting.field_season).joinedload(FieldSeason.cluster),
        )
        .filter_by(id=planting_id).first_or_404()
    )
    if planting.field_season.season_id != season.id:
        abort(404)
    return planting


def _items():
    types = TreatmentType.query.order_by(TreatmentType.name).all()
    products = Product.query.options(joinedload(Product.unit)).filter(
        Product.is_archived.is_(False)
    ).order_by(Product.name).all()
    return types, products


def _number(raw, description):
    try:
        amount = Decimal(str(raw or "").replace(",", "."))
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation()
        return amount
    except (InvalidOperation, ValueError):
        raise ValueError(f"{description}: введіть додатне число.")


def _parse_operations(planting, types, products):
    type_ids = {x.id for x in types}
    product_map = {x.id: x for x in products}
    try:
        count = int(request.form.get("operation_count", "0"))
    except ValueError:
        raise ValueError("Некоректна кількість операцій.")
    if not 1 <= count <= 60:
        raise ValueError("Потрібна хоча б одна операція (максимум 60).")
    result = []
    for i in range(count):
        base = f"operations-{i}-"
        try:
            type_id = int(request.form.get(base + "type", ""))
            product_count = int(request.form.get(base + "product_count", "0"))
        except ValueError:
            raise ValueError(f"Операція {i+1}: перевірте тип та кількість препаратів.")
        if type_id not in type_ids or not 1 <= product_count <= 20:
            raise ValueError(f"Операція {i+1}: потрібен тип і 1–20 препаратів.")
        basis_unit = request.form.get(base + "basis_unit", "ha")
        if basis_unit not in ("ha", "t"):
            raise ValueError("Невідома база розрахунку.")
        basis = _number(request.form.get(base + "basis_quantity"), "Обсяг обробки")
        if basis_unit == "ha" and basis > planting.area:
            raise ValueError("Площа операції не може перевищувати площу посіву.")
        day_text = request.form.get(base + "planned_date", "").strip()
        try:
            planned_date = date.fromisoformat(day_text) if day_text else None
        except ValueError:
            raise ValueError("Перевірте дату операції.")
        bbch = request.form.get(base + "bbch", "").strip()[:30]
        label = request.form.get(base + "label", "").strip()[:180]
        entries, seen = [], set()
        for j in range(product_count):
            prefix = base + f"products-{j}-"
            try:
                product_id = int(request.form.get(prefix + "id", ""))
            except ValueError:
                raise ValueError(f"Операція {i+1}: оберіть препарат.")
            if product_id not in product_map:
                raise ValueError(f"Операція {i+1}: продукт недоступний або архівований.")
            if product_id in seen:
                raise ValueError(f"Операція {i+1}: однаковий препарат не можна повторювати.")
            seen.add(product_id)
            rate = _number(request.form.get(prefix + "rate"), "Норма препарату")
            qty = (basis * rate).quantize(_QTY, rounding=ROUND_HALF_UP)
            if qty <= 0:
                raise ValueError("Розрахована кількість препарату занадто мала.")
            product = product_map[product_id]
            entries.append(dict(product_id=product_id, rate=rate, quantity=qty,
                                unit_snapshot=(product.unit.name if product.unit else "")))
        result.append(dict(position=i + 1, treatment_type_id=type_id, label=label,
                           bbch=bbch or None, planned_date=planned_date,
                           basis_unit=basis_unit, basis_quantity=basis,
                           products=entries))
    return result


def _form_rows(plan, planting):
    if plan is None or not plan.operations:
        return [dict(type_id="", label="", bbch="", planned_date="",
                     basis_unit="ha", basis_quantity=str(planting.area),
                     products=[dict(id="", rate="")])]
    return [
        dict(type_id=o.treatment_type_id, label=o.label or "", bbch=o.bbch or "",
             planned_date=o.planned_date.isoformat() if o.planned_date else "",
             basis_unit=o.basis_unit, basis_quantity=str(o.basis_quantity),
             products=[dict(id=p.product_id, rate=str(p.rate)) for p in o.products])
        for o in plan.operations
    ]


def _available_field_seasons(season):
    """Only one-crop fields without a legacy or pilot plan are selectable.

    The sowing structure is authoritative. A field with several crop allocations
    must first be divided into distinct fields in that structure.
    """
    if season.is_closed:
        return []
    legacy_used = {
        field_id for (field_id,) in db.session.query(Plan.field_id)
        .filter(Plan.season_id == season.id).all()
    }
    workspace_used = {
        fs_id for (fs_id,) in db.session.query(FieldPlanting.field_season_id)
        .join(TechnologyPlan, TechnologyPlan.planting_id == FieldPlanting.id)
        .filter(TechnologyPlan.season_id == season.id).all()
    }
    records = (
        FieldSeason.query.join(Field, FieldSeason.field_id == Field.id)
        .options(
            joinedload(FieldSeason.field),
            joinedload(FieldSeason.company),
            joinedload(FieldSeason.cluster),
            joinedload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        )
        .filter(FieldSeason.season_id == season.id)
        .order_by(Field.name).all()
    )
    return [
        r for r in records
        if r.field_id not in legacy_used
        and r.id not in workspace_used
        and len(r.plantings) == 1
    ]


def _another_plan_exists(planting, season):
    record = planting.field_season
    if Plan.query.filter_by(field_id=record.field_id, season_id=season.id).first():
        return True
    return bool(
        TechnologyPlan.query.join(
            FieldPlanting, TechnologyPlan.planting_id == FieldPlanting.id
        ).filter(
            TechnologyPlan.season_id == season.id,
            FieldPlanting.field_season_id == record.id,
        ).first()
    )


@bp.get("/create/cluster")
def select_cluster():
    records = _available_field_seasons(current())
    clusters = sorted({r.cluster_id: r.cluster for r in records}.values(),
                      key=lambda c: c.name)
    return render_template("planning_workspace/select_cluster.html",
                           clusters=clusters, **context())


@bp.get("/create/cluster/<int:cluster_id>/company")
def select_company(cluster_id):
    records = [r for r in _available_field_seasons(current())
               if r.cluster_id == cluster_id]
    companies = sorted({r.company_id: r.company for r in records}.values(),
                       key=lambda c: c.name)
    return render_template("planning_workspace/select_company.html",
                           companies=companies, cluster_id=cluster_id, **context())


@bp.get("/create/cluster/<int:cluster_id>/company/<int:company_id>/field")
def select_field(cluster_id, company_id):
    records = [r for r in _available_field_seasons(current())
               if r.cluster_id == cluster_id and r.company_id == company_id]
    return render_template("planning_workspace/select_field.html",
                           rows=records, cluster_id=cluster_id, company_id=company_id,
                           **context())


@bp.get("/")
def index():
    season = current()
    rows = (FieldPlanting.query
            .join(FieldSeason, FieldPlanting.field_season_id == FieldSeason.id)
            .join(Field, FieldSeason.field_id == Field.id)
            .options(
                joinedload(FieldPlanting.culture),
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.field),
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.company),
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.cluster),
            )
            .filter(FieldSeason.season_id == season.id)
            .order_by(Field.name, FieldPlanting.id).all())
    cluster_id = request.args.get("cluster_id", type=int)
    company_id = request.args.get("company_id", type=int)
    culture_id = request.args.get("culture_id", type=int)
    status = request.args.get("status", "")
    all_clusters = sorted({(p.field_season.cluster.id, p.field_season.cluster.name) for p in rows},
                          key=lambda v: v[1])
    cluster_rows = [p for p in rows if not cluster_id or p.field_season.cluster_id == cluster_id]
    companies = sorted({(p.field_season.company.id, p.field_season.company.name) for p in cluster_rows},
                       key=lambda v: v[1])
    company_rows = [p for p in cluster_rows if not company_id or p.field_season.company_id == company_id]
    cultures = sorted({(p.culture.id, p.culture.name) for p in company_rows}, key=lambda v: v[1])
    plans = {p.planting_id: p for p in TechnologyPlan.query.filter_by(season_id=season.id)}
    company_rows = [p for p in company_rows if p.id in plans]
    filtered = [p for p in company_rows
                if (not culture_id or p.culture_id == culture_id)
                and (not status or (plans[p.id].status if p.id in plans else "none") == status)]
    return render_template("planning_workspace/index.html", rows=filtered,
                           plans=plans, clusters=all_clusters, companies=companies,
                           cultures=cultures, cluster_id=cluster_id,
                           company_id=company_id, culture_id=culture_id, status=status,
                           **context())


@bp.route("/planting/<int:planting_id>", methods=["GET", "POST"])
def edit(planting_id):
    season = writable() if request.method == "POST" else current()
    planting = _planting(planting_id, season)
    plan = TechnologyPlan.query.filter_by(planting_id=planting.id).first()
    if plan is None:
        if len(planting.field_season.plantings) != 1:
            abort(409, description="Спочатку розділіть поле з кількома культурами у структурі посівів.")
        if _another_plan_exists(planting, season):
            abort(409, description="Для цього поля вже є план у вибраному сезоні.")
    types, products = _items()
    form = ActionForm()
    if request.method == "POST":
        validate_posted_season(season)
        if plan is not None and plan.status == "approved":
            abort(409, description="Затверджений план спочатку потрібно повернути на доопрацювання.")
        if not form.validate_on_submit():
            abort(400, description="Недійсна форма.")
        try:
            operations = _parse_operations(planting, types, products)
        except ValueError as exc:
            flash(str(exc), "warning")
        else:
            if plan is None:
                plan = TechnologyPlan(season_id=season.id, planting_id=planting.id)
                db.session.add(plan)
                db.session.flush()
            # Editing a ready plan creates a draft again, never silently stays ready.
            plan.status = "draft"
            plan.approved_at = None
            plan.operations.clear()
            db.session.flush()
            for attrs in operations:
                materials = attrs.pop("products")
                operation = TechnologyOperation(plan=plan, **attrs)
                db.session.add(operation)
                for material in materials:
                    operation.products.append(TechnologyProduct(**material))
            db.session.commit()
            flash("Чернетку технологічного плану збережено.", "success")
            return redirect(url_for("planning_workspace.edit", planting_id=planting.id))
    return render_template(
        "planning_workspace/edit.html", planting=planting, plan=plan, form=form,
        types=types, products=products, initial_rows=_form_rows(plan, planting),
        **context(),
    )


@bp.post("/<int:plan_id>/status")
def set_status(plan_id):
    season = writable()
    plan = TechnologyPlan.query.filter_by(id=plan_id, season_id=season.id).first_or_404()
    validate_posted_season(season)
    if not ActionForm().validate_on_submit():
        abort(400, description="Недійсна форма.")
    action = request.form.get("action", "")
    if action == "ready" and plan.status == "draft" and plan.operations:
        plan.status = "ready"
    elif action == "revise" and plan.status == "ready":
        plan.status = "draft"
    elif action == "approve" and plan.status == "ready" and is_admin():
        plan.status = "approved"
        plan.approved_at = datetime.utcnow()
    elif action == "unlock" and plan.status == "approved" and is_admin():
        plan.status = "draft"
        plan.approved_at = None
    else:
        abort(403 if action in ("approve", "unlock") and not is_admin() else 409)
    db.session.commit()
    flash("Статус технологічного плану змінено.", "success")
    return redirect(url_for("planning_workspace.edit", planting_id=plan.planting_id))
