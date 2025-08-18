# modules/purchases/payer_allocation/services.py
from sqlalchemy import func
from datetime import datetime
from extensions import db
from modules.plans.models import Plan, Treatment
from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from .models import PayerAllocation

def sync_from_plans() -> dict:
    """
    Синхронізація з планів:
    - агрегує кількість по (field_id, product_id) тільки з затверджених планів;
    - upsert у payer_allocations (оновлює qty/атрибути, не чіпає payer_id);
    - рядки, яких більше немає у планах, помічає як stale.
    Повертає лічильники: added/updated/marked_stale/total_active
    """
    # 1) Агрегація з планів
    subq = (
        db.session.query(
            Plan.field_id.label("field_id"),
            Field.company_id.label("company_id"),
            Treatment.product_id.label("product_id"),
            func.sum(Treatment.quantity).label("qty"),
        )
        .join(Field, Field.id == Plan.field_id)
        .join(Treatment, Treatment.plan_id == Plan.id)
        .filter(Plan.is_approved.is_(True))  # беремо лише затверджені
        .group_by(Plan.field_id, Field.company_id, Treatment.product_id)
        .subquery()
    )

    # Заберемо виробника та одиницю з продукту
    rows = (
        db.session.query(
            subq.c.field_id,
            subq.c.company_id,
            subq.c.product_id,
            subq.c.qty,
            Product.manufacturer_id,
            Product.unit_id,
        )
        .join(Product, Product.id == subq.c.product_id)
        .all()
    )

    # 2) Існуючі ключі
    existing = {
        (pa.field_id, pa.product_id): pa
        for pa in db.session.query(PayerAllocation).all()
    }
    seen_keys = set()

    added = 0
    updated = 0

    # 3) Upsert
    for r in rows:
        key = (r.field_id, r.product_id)
        seen_keys.add(key)

        if key in existing:
            pa = existing[key]
            # Оновлюємо атрибути/qty, payer_id НЕ чіпаємо
            changed = False
            if pa.company_id != r.company_id:
                pa.company_id = r.company_id; changed = True
            if pa.manufacturer_id != r.manufacturer_id:
                pa.manufacturer_id = r.manufacturer_id; changed = True
            if pa.unit_id != r.unit_id:
                pa.unit_id = r.unit_id; changed = True
            if str(pa.qty) != str(r.qty or 0):
                pa.qty = r.qty or 0; changed = True
            if pa.status != "active":
                pa.status = "active"; changed = True
            if changed:
                updated += 1
        else:
            pa = PayerAllocation(
                field_id=r.field_id,
                company_id=r.company_id,
                product_id=r.product_id,
                manufacturer_id=r.manufacturer_id,
                unit_id=r.unit_id,
                qty=r.qty or 0,
                status="active",
            )
            db.session.add(pa)
            added += 1

    # 4) Позначаємо відсутні у планах як stale
    marked_stale = 0
    for key, pa in existing.items():
        if key not in seen_keys and pa.status != "stale":
            pa.status = "stale"
            marked_stale += 1

    db.session.commit()

    total_active = db.session.query(PayerAllocation).filter_by(status="active").count()
    return dict(added=added, updated=updated, marked_stale=marked_stale, total_active=total_active)
