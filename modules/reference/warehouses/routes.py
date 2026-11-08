"""Warehouse reference directory with company ownership and safe lifecycle.

Legacy warehouse IDs are referenced by stock_transactions.warehouse_id
WITHOUT a PostgreSQL foreign key. Never physically delete a warehouse,
and never reassign a warehouse with stock history to another company.
The public active-warehouse JSON API is kept unchanged.
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from wtforms_sqlalchemy.fields import QuerySelectField

from extensions import db
from modules.reference.companies.models import Company
from modules.reference.shared_crud import normalize_reference_name
from modules.warehouse.models import StockTransaction
from .models import Warehouse


warehouses_bp = Blueprint(
    "warehouses",
    __name__,
    url_prefix="/reference/warehouses",
    template_folder="templates",
)


def _companies():
    return Company.query.order_by(Company.name).all()


class WarehouseForm(FlaskForm):
    company = QuerySelectField(
        "Підприємство",
        query_factory=_companies, get_label="name",
        allow_blank=True, blank_text="— Оберіть підприємство —",
        validators=[DataRequired(message="Оберіть підприємство.")],
    )
    name = StringField(
        "Назва складу",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву складу."),
            Length(max=255, message="Назва не може перевищувати 255 символів."),
        ],
    )
    address = StringField(
        "Адреса / примітка",
        filters=[normalize_reference_name],
        validators=[Optional(), Length(max=255, message="Адреса не може перевищувати 255 символів.")],
    )
    is_active = BooleanField("Активний", default=True)
    submit = SubmitField("Зберегти")


class WarehouseActionForm(FlaskForm):
    """CSRF token for changing a warehouse's active state."""


def _existing(name, company_id, exclude_id=None):
    query = Warehouse.query.filter(
        Warehouse.company_id == company_id,
        func.lower(Warehouse.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(Warehouse.id != exclude_id)
    return query.first()


def _stock_counts():
    # This reference is NOT declared as an FK in the current database.
    return dict(
        db.session.query(StockTransaction.warehouse_id, func.count(StockTransaction.id))
        .group_by(StockTransaction.warehouse_id)
        .all()
    )


def _render_form(form, warehouse, title):
    return render_template(
        "warehouses/form.html",
        form=form, warehouse=warehouse, title=title,
        create_url=url_for("warehouses.new"),
    )


@warehouses_bp.get("/")
def index():
    company_id = request.args.get("company_id", type=int)
    active = request.args.get("active")
    search = (request.args.get("q") or "").strip()

    query = Warehouse.query.options(joinedload(Warehouse.company))
    if company_id:
        query = query.filter(Warehouse.company_id == company_id)
    if active in ("0", "1"):
        query = query.filter(Warehouse.is_active.is_(active == "1"))
    if search:
        query = query.filter(Warehouse.name.ilike(f"%{search}%"))

    return render_template(
        "warehouses/index.html",
        rows=query.order_by(Warehouse.company_id, Warehouse.name).all(),
        companies=_companies(),
        company_id=company_id, active=active, q=search,
        stock_counts=_stock_counts(),
        action_form=WarehouseActionForm(),
        create_url=url_for("warehouses.new"),
    )


@warehouses_bp.get("/new")
def new():
    form = WarehouseForm()
    company_id = request.args.get("company_id", type=int)
    if company_id:
        form.company.data = Company.query.get(company_id)
    return _render_form(form, None, "Новий склад")


@warehouses_bp.post("/new")
def create():
    form = WarehouseForm()
    if form.validate_on_submit():
        if _existing(form.name.data, form.company.data.id):
            form.name.errors.append("Склад із такою назвою вже існує в цьому підприємстві.")
        else:
            warehouse = Warehouse(
                company_id=form.company.data.id, name=form.name.data,
                address=form.address.data or None, is_active=bool(form.is_active.data),
            )
            try:
                db.session.add(warehouse)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося створити склад: перевірте назву й підприємство.")
            else:
                flash("Склад створено.", "success")
                return redirect(url_for("warehouses.index", company_id=warehouse.company_id))
    return _render_form(form, None, "Новий склад")


@warehouses_bp.get("/<int:wid>/edit")
def edit(wid):
    warehouse = Warehouse.query.get_or_404(wid)
    form = WarehouseForm(obj=warehouse)
    return _render_form(form, warehouse, "Редагувати склад")


@warehouses_bp.post("/<int:wid>/edit")
def update(wid):
    warehouse = Warehouse.query.get_or_404(wid)
    form = WarehouseForm()
    if form.validate_on_submit():
        operations = StockTransaction.query.filter_by(warehouse_id=warehouse.id).count()
        if warehouse.company_id != form.company.data.id and operations:
            form.company.errors.append(
                "Цей склад має складські операції. Перенести його до іншого підприємства не можна."
            )
        elif _existing(form.name.data, form.company.data.id, exclude_id=warehouse.id):
            form.name.errors.append("Склад із такою назвою вже існує в цьому підприємстві.")
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
    return _render_form(form, warehouse, "Редагувати склад")


@warehouses_bp.post("/<int:wid>/toggle")
def toggle(wid):
    if not WarehouseActionForm().validate_on_submit():
        abort(400)
    warehouse = Warehouse.query.get_or_404(wid)
    warehouse.is_active = not bool(warehouse.is_active)
    db.session.commit()
    flash(
        "Склад активовано." if warehouse.is_active else "Склад деактивовано. Історія збережена.",
        "success",
    )
    return redirect(url_for("warehouses.index", company_id=warehouse.company_id))


@warehouses_bp.post("/<int:wid>/delete")
def delete(wid):
    """Backward-compatible endpoint: archive, never delete the actual row."""
    if not WarehouseActionForm().validate_on_submit():
        abort(400)
    warehouse = Warehouse.query.get_or_404(wid)
    warehouse.is_active = False
    db.session.commit()
    flash("Склад деактивовано. Історія складських операцій збережена.", "info")
    return redirect(url_for("warehouses.index", company_id=warehouse.company_id))


@warehouses_bp.get("/api/by_company")
def api_by_company():
    """Keep existing [{id, name, address}] contract for shipment forms."""
    company_id = request.args.get("company_id", type=int)
    if not company_id:
        return jsonify([])
    rows = Warehouse.active_for_company(company_id).all()
    return jsonify([
        {"id": warehouse.id, "name": warehouse.name, "address": warehouse.address}
        for warehouse in rows
    ])
