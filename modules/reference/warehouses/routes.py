"""Warehouse directory: company-linked, soft-deleted and safe for stock history."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from extensions import db

from .models import Warehouse
from .forms import WarehouseForm, WarehouseActionForm
from modules.reference.companies.models import Company

warehouses_bp = Blueprint(
    "warehouses", __name__,
    url_prefix="/reference/warehouses",
    template_folder="templates",
)


def _existing(name, company_id, exclude_id=None):
    query = Warehouse.query.filter(
        Warehouse.company_id == company_id,
        func.lower(Warehouse.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(Warehouse.id != exclude_id)
    return query.first()


def _stock_usage_count(warehouse_id):
    # Legacy stock_transactions.warehouse_id has no declared FK, but the
    # relation is meaningful; changing its owner would corrupt history.
    from modules.warehouse.models import StockTransaction
    return StockTransaction.query.filter_by(warehouse_id=warehouse_id).count()


@warehouses_bp.get("/")
def index():
    company_id = request.args.get("company_id", type=int)
    active = request.args.get("active")
    term = (request.args.get("q") or "").strip()
    query = Warehouse.query.options(joinedload(Warehouse.company))
    if company_id:
        query = query.filter(Warehouse.company_id == company_id)
    if active in ("0", "1"):
        query = query.filter(Warehouse.is_active.is_(active == "1"))
    if term:
        query = query.filter(Warehouse.name.ilike(f"%{term}%"))
    return render_template(
        "warehouses/index.html",
        rows=query.order_by(Warehouse.company_id, Warehouse.name).all(),
        companies=Company.query.order_by(Company.name).all(),
        company_id=company_id, active=active, q=term,
        action_form=WarehouseActionForm(),
        create_url=url_for("warehouses.new"),
    )


def _form_response(form, warehouse, title):
    return render_template(
        "warehouses/form.html", form=form, warehouse=warehouse, title=title,
    )


@warehouses_bp.get("/new")
def new():
    form = WarehouseForm()
    company_id = request.args.get("company_id", type=int)
    if company_id:
        form.company.data = Company.query.get(company_id)
    return _form_response(form, None, "Новий склад")


@warehouses_bp.post("/new")
def create():
    form = WarehouseForm()
    if form.validate_on_submit():
        if _existing(form.name.data, form.company.data.id):
            form.name.errors.append("Такий склад уже існує в цьому підприємстві.")
        else:
            warehouse = Warehouse(
                name=form.name.data, company_id=form.company.data.id,
                address=form.address.data or None,
                is_active=bool(form.is_active.data),
            )
            try:
                db.session.add(warehouse)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти склад: перевірте назву та підприємство.")
            else:
                flash("Склад створено.", "success")
                return redirect(url_for("warehouses.index", company_id=warehouse.company_id))
    return _form_response(form, None, "Новий склад")


@warehouses_bp.get("/<int:wid>/edit")
def edit(wid):
    warehouse = Warehouse.query.get_or_404(wid)
    form = WarehouseForm(obj=warehouse)
    form.company.data = warehouse.company
    return _form_response(form, warehouse, "Редагування складу")


@warehouses_bp.post("/<int:wid>/edit")
def update(wid):
    warehouse = Warehouse.query.get_or_404(wid)
    form = WarehouseForm()
    if form.validate_on_submit():
        if warehouse.company_id != form.company.data.id and _stock_usage_count(wid):
            form.company.errors.append("Склад має складські операції. Зміну підприємства заблоковано.")
        elif _existing(form.name.data, form.company.data.id, exclude_id=wid):
            form.name.errors.append("Такий склад уже існує в обраному підприємстві.")
        else:
            warehouse.company_id = form.company.data.id
            warehouse.name = form.name.data
            warehouse.address = form.address.data or None
            warehouse.is_active = bool(form.is_active.data)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти зміни.")
            else:
                flash("Склад оновлено.", "success")
                return redirect(url_for("warehouses.index", company_id=warehouse.company_id))
    return _form_response(form, warehouse, "Редагування складу")


@warehouses_bp.post("/<int:wid>/toggle")
def toggle(wid):
    if not WarehouseActionForm().validate_on_submit():
        abort(400)
    warehouse = Warehouse.query.get_or_404(wid)
    warehouse.is_active = not bool(warehouse.is_active)
    db.session.commit()
    flash("Склад активовано." if warehouse.is_active else "Склад деактивовано.", "success")
    return redirect(url_for("warehouses.index", company_id=warehouse.company_id))


@warehouses_bp.post("/<int:wid>/delete")
def delete(wid):
    """Retain existing soft-delete endpoint for historical warehouse records."""
    if not WarehouseActionForm().validate_on_submit():
        abort(400)
    warehouse = Warehouse.query.get_or_404(wid)
    warehouse.is_active = False
    db.session.commit()
    flash("Склад деактивовано. Його історія збережена.", "info")
    return redirect(url_for("warehouses.index", company_id=warehouse.company_id))


@warehouses_bp.get("/api/by_company")
def api_by_company():
    company_id = request.args.get("company_id", type=int)
    if not company_id:
        return jsonify([])
    rows = Warehouse.active_for_company(company_id).all()
    return jsonify([{"id": w.id, "name": w.name, "address": w.address} for w in rows])
