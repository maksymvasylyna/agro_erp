"""Shared guards for state-changing planning endpoints.

Never trust a template button or a GET URL to authorize mutations.
Every sensitive transition must use POST + CSRF + active-season match.
"""
from flask import abort
from extensions import db
from flask_wtf import FlaskForm

from admin_auth import is_admin
from modules.plans.season import validate_posted_season, writable


class PlanActionForm(FlaskForm):
    """CSRF-only form for state-changing planning actions."""
    pass


def verify_plan_action(*, admin=False):
    season = writable()
    validate_posted_season(season)
    if not PlanActionForm().validate_on_submit():
        abort(400, description="Некоректний або застарілий запит. Оновіть сторінку.")
    if admin and not is_admin():
        abort(403, description="Ця дія доступна лише адміністратору.")
    return season


def prepare_treatments(form, area):
    """Validate lines and compute quantities from trusted seasonal area.

    Hidden/readonly browser fields never determine the final quantity,
    manufacturer or unit. Return unsaved Treatment objects for one transaction.
    """
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    from modules.plans.models import Treatment
    from modules.reference.products.models import Product

    entries = form.treatments.entries
    if not 1 <= len(entries) <= 300:
        abort(400, description="План повинен містити від 1 до 300 обробітків.")
    try:
        hectares = Decimal(str(area))
        if not hectares.is_finite() or hectares <= 0:
            raise InvalidOperation()
    except (ValueError, InvalidOperation):
        abort(409, description="Площа поля в структурі посівів некоректна.")
    result = []
    for row in entries:
        try:
            rate = Decimal(str(row.rate.data))
            if not rate.is_finite() or not Decimal("0") < rate <= Decimal("1000000"):
                raise InvalidOperation()
            quantity = (hectares * rate).quantize(Decimal("0.001"),
                                                 rounding=ROUND_HALF_UP)
            if not quantity.is_finite() or quantity <= 0 or quantity > Decimal("1000000000000"):
                raise InvalidOperation()
        except (ValueError, InvalidOperation):
            abort(400, description="Вкажіть коректну додатну норму внесення.")
        product = db.session.get(Product, row.product_id.data)
        if product is None or product.is_archived:
            abort(400, description="Продукт недоступний або архівований.")
        result.append(Treatment(
            treatment_type_id=row.treatment_type_id.data,
            product_id=product.id,
            rate=float(rate),
            unit=product.unit.name if product.unit else "",
            manufacturer=product.manufacturer.name if product.manufacturer else "",
            quantity=float(quantity),
        ))
    return result
