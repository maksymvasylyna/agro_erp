# -*- coding: utf-8 -*-
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy.exc import IntegrityError
from extensions import db
from .models import Warehouse
from modules.reference.companies.models import Company

warehouses_bp = Blueprint(
    "warehouses",
    __name__,
    url_prefix="/reference/warehouses",
    template_folder="templates",
)

# ───────────────────────────── Helpers ─────────────────────────────

def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default

def _company_list():
    return Company.query.order_by(Company.name.asc()).all()

# ───────────────────────────── Views ─────────────────────────────

@warehouses_bp.get("/")
def index():
    """Список складів із фільтрами: компанія, активність, пошук за назвою."""
    company_id = request.args.get("company_id", type=int)
    active = request.args.get("active")  # "1"|"0"|None
    q = request.args.get("q", type=str)

    query = Warehouse.query

    if company_id:
        query = query.filter(Warehouse.company_id == company_id)
    if active in ("0", "1"):
        query = query.filter(Warehouse.is_active.is_(active == "1"))
    if q:
        query = query.filter(Warehouse.name.ilike(f"%{q.strip()}%"))

    rows = query.order_by(Warehouse.company_id.asc(), Warehouse.name.asc()).all()

    return render_template(
        "warehouses/index.html",
        rows=rows,
        companies=_company_list(),
        company_id=company_id,
        active=active,
        q=q or "",
        title="Довідник складів",
        header="🏷️ Довідник складів підприємств",
    )


@warehouses_bp.get("/new")
def new():
    """Форма створення складу."""
    company_id = request.args.get("company_id", type=int)
    return render_template(
        "warehouses/form.html",
        title="Новий склад",
        header="➕ Новий склад",
        companies=_company_list(),
        warehouse=None,
        company_id=company_id,
        action=url_for("warehouses.create"),
        submit_label="Створити",
    )


@warehouses_bp.post("/new")
def create():
    """Створення складу."""
    name = (request.form.get("name") or "").strip()
    address = (request.form.get("address") or "").strip() or None
    company_id = request.form.get("company_id", type=int)
    is_active = request.form.get("is_active") in ("on", "1", "true", "True")

    if not company_id:
        flash("Оберіть підприємство.", "warning")
        return redirect(url_for("warehouses.new"))

    if not name:
        flash("Вкажіть назву складу.", "warning")
        return redirect(url_for("warehouses.new", company_id=company_id))

    w = Warehouse(company_id=company_id, name=name, address=address, is_active=is_active)
    db.session.add(w)
    try:
        db.session.commit()
        flash("Склад створено.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Склад із такою назвою вже існує в обраній компанії.", "danger")

    return redirect(url_for("warehouses.index", company_id=company_id))


@warehouses_bp.get("/<int:wid>/edit")
def edit(wid: int):
    """Форма редагування складу."""
    w = Warehouse.query.get_or_404(wid)
    return render_template(
        "warehouses/form.html",
        title="Редагування складу",
        header=f"✏️ Редагування складу: {w.name}",
        companies=_company_list(),
        warehouse=w,
        company_id=w.company_id,
        action=url_for("warehouses.update", wid=w.id),
        submit_label="Зберегти",
    )


@warehouses_bp.post("/<int:wid>/edit")
def update(wid: int):
    """Оновлення складу."""
    w = Warehouse.query.get_or_404(wid)

    name = (request.form.get("name") or "").strip()
    address = (request.form.get("address") or "").strip() or None
    company_id = request.form.get("company_id", type=int)
    is_active = request.form.get("is_active") in ("on", "1", "true", "True")

    if not company_id:
        flash("Оберіть підприємство.", "warning")
        return redirect(url_for("warehouses.edit", wid=wid))

    if not name:
        flash("Вкажіть назву складу.", "warning")
        return redirect(url_for("warehouses.edit", wid=wid))

    w.company_id = company_id
    w.name = name
    w.address = address
    w.is_active = is_active

    try:
        db.session.commit()
        flash("Зміни збережено.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Склад із такою назвою вже існує в обраній компанії.", "danger")

    return redirect(url_for("warehouses.index", company_id=company_id))


@warehouses_bp.post("/<int:wid>/toggle")
def toggle(wid: int):
    """Швидке увімк/вимк активності."""
    w = Warehouse.query.get_or_404(wid)
    w.is_active = not bool(w.is_active)
    db.session.commit()
    flash(("Склад активовано." if w.is_active else "Склад деактивовано."), "success")
    return redirect(url_for("warehouses.index", company_id=w.company_id))


@warehouses_bp.post("/<int:wid>/delete")
def delete(wid: int):
    """
    М'яке видалення: просто деактивуємо.
    За потреби можна зробити повне видалення (але це ризиковано, якщо є посилання).
    """
    w = Warehouse.query.get_or_404(wid)
    w.is_active = False
    db.session.commit()
    flash("Склад деактивовано.", "success")
    return redirect(url_for("warehouses.index", company_id=w.company_id))

# ───────────────────────────── API (для форм) ─────────────────────────────

@warehouses_bp.get("/api/by_company")
def api_by_company():
    """
    JSON для підвантаження складів-одержувачів у формах:
      /reference/warehouses/api/by_company?company_id=123
    Повертає [{id, name, address}]
    """
    company_id = request.args.get("company_id", type=int)
    if not company_id:
        return jsonify([])

    rows = Warehouse.active_for_company(company_id).all()
    return jsonify([{"id": w.id, "name": w.name, "address": w.address} for w in rows])
