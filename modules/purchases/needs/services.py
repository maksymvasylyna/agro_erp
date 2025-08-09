from extensions import db
from sqlalchemy.orm import joinedload

from modules.plans.models import Plan, Treatment
from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.units.models import Unit


def get_summary_data(company_id=None, culture_id=None, product_id=None):
    query = (
        db.session.query(Treatment)
        .join(Treatment.plan)  # 👈 обовʼязково через звʼязок
        .join(Treatment.product)
        .join(Plan.field)
        .options(
            joinedload(Treatment.product).joinedload(Product.unit),
            joinedload(Treatment.plan).joinedload(Plan.field).joinedload(Field.company),
            joinedload(Treatment.plan).joinedload(Plan.field).joinedload(Field.culture)
        )
        .filter(Plan.is_approved.is_(True))  # 👈 правильне фільтрування
    )

    # Застосовуємо фільтри
    if company_id:
        query = query.filter(Field.company_id == company_id)
    if culture_id:
        query = query.filter(Field.culture_id == culture_id)
    if product_id:
        query = query.filter(Treatment.product_id == product_id)

    treatments = query.all()
    result = []

    for t in treatments:
        plan = t.plan
        field = plan.field
        product = t.product

        area = field.area or 0
        rate = t.rate or 0
        quantity = round(area * rate, 1)

        result.append({
            "company": field.company.name if field.company else "—",
            "product": product.name,
            "culture": field.culture.name if field.culture else "—",
            "quantity": quantity,
            "unit": product.unit.name if product.unit else "—"
        })

    return result
