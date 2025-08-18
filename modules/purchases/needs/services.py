# modules/purchases/needs/services.py
from sqlalchemy import func
from extensions import db

from modules.plans.models import Plan, Treatment
from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from modules.reference.cultures.models import Culture
from modules.reference.companies.models import Company

def get_summary(company_id=None, culture_id=None, product_id=None):
    """
    Зведена потреба ТІЛЬКИ з затверджених планів.
    Агрегує Treatment.quantity по Product, з урахуванням Company (з поля) і Culture (з поля).
    Повертає: [{product_id, product_name, culture_name, company_name, qty}]
    """

    q = (
        db.session.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Culture.name.label("culture_name"),
            Company.name.label("company_name"),
            func.coalesce(func.sum(Treatment.quantity), 0).label("qty"),
        )
        .join(Plan, Treatment.plan_id == Plan.id)
        .join(Field, Field.id == Plan.field_id)
        .join(Company, Company.id == Field.company_id)
        .outerjoin(Culture, Culture.id == Field.culture_id)   # культура може бути відсутня
        .join(Product, Product.id == Treatment.product_id)
        .filter(Plan.is_approved.is_(True))                   # ключова умова
        .group_by(Product.id, Product.name, Culture.name, Company.name)
        .order_by(Product.name.asc())
    )

    if company_id:
        q = q.filter(Field.company_id == company_id)
    if culture_id:
        q = q.filter(Field.culture_id == culture_id)
    if product_id:
        q = q.filter(Treatment.product_id == product_id)

    rows = q.all()
    return [
        {
            "product_id": r.product_id,
            "product_name": r.product_name,
            "culture_name": r.culture_name or "—",
            "company_name": r.company_name or "—",
            "qty": float(r.qty or 0),
        }
        for r in rows
    ]
