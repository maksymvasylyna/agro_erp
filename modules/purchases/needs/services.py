# modules/purchases/needs/services.py
from sqlalchemy import func, case
from extensions import db
from modules.plans.approved_plans.models import ApprovedPlan, ApprovedPlanItem  # підстав свої імена моделей
from modules.reference.products.models import Product
from modules.reference.cultures.models import Culture
from modules.reference.companies.models import Company
# Якщо маєш Units/коефіцієнти — імпортуй і додай конвертацію нижче

def get_summary(company_id=None, culture_id=None, product_id=None):
    """
    Повертає зведену потребу з ТІЛЬКИ затверджених планів.
    Фільтри опційні: company_id, culture_id, product_id.
    Повертає список dict: {product_id, product_name, culture_name, company_name, qty}
    """

    q = (
        db.session.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Culture.name.label("culture_name"),
            Company.name.label("company_name"),
            # Якщо потрібна конвертація одиниць, заміни ApprovedPlanItem.qty на нормалізовану величину
            func.coalesce(func.sum(ApprovedPlanItem.qty), 0).label("qty")
        )
        .join(ApprovedPlan, ApprovedPlan.id == ApprovedPlanItem.plan_id)
        .join(Product, Product.id == ApprovedPlanItem.product_id)
        .join(Culture, Culture.id == ApprovedPlan.culture_id)
        .join(Company, Company.id == ApprovedPlan.company_id)
        .filter(ApprovedPlan.status == "approved")  # критично: тільки затверджені
        .group_by(Product.id, Product.name, Culture.name, Company.name)
        .order_by(Product.name.asc())
    )

    if company_id:
        q = q.filter(ApprovedPlan.company_id == company_id)
    if culture_id:
        q = q.filter(ApprovedPlan.culture_id == culture_id)
    if product_id:
        q = q.filter(ApprovedPlanItem.product_id == product_id)

    rows = q.all()

    return [
        {
            "product_id": r.product_id,
            "product_name": r.product_name,
            "culture_name": r.culture_name,
            "company_name": r.company_name,
            "qty": float(r.qty or 0),
        }
        for r in rows
    ]
