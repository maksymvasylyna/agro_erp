from flask import Blueprint, render_template, request
from extensions import db
from modules.plans.models import Plan, Treatment
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from .forms import NeedsFilterForm

needs_bp = Blueprint(
    'needs',
    __name__,
    url_prefix='/purchases/needs',
    template_folder='templates'
)

@needs_bp.route('/summary', methods=['GET'])
def summary():
    form = NeedsFilterForm(request.args)

    # ✅ Підтягуємо одиницю виміру через джойн
    query = (
        db.session.query(
            Company.name.label("company"),
            Product.name.label("product"),
            Culture.name.label("culture"),
            db.func.sum(Treatment.quantity).label("quantity"),
            Unit.name.label("unit")
        )
        .join(Plan, Treatment.plan_id == Plan.id)
        .join(Company, Plan.field.has(Company.id == Company.id))
        .join(Culture, Plan.field.has(Culture.id == Culture.id), isouter=True)
        .join(Product, Treatment.product_id == Product.id)
        .join(Unit, Product.unit_id == Unit.id, isouter=True)
        .filter(Plan.is_approved == True)
        .group_by(Company.name, Product.name, Culture.name, Unit.name)
    )

    # Фільтри
    if form.company_id.data:
        query = query.filter(Company.id == form.company_id.data)

    if form.culture_id.data:
        query = query.filter(Culture.id == form.culture_id.data)

    if form.product_id.data:
        query = query.filter(Product.id == form.product_id.data)

    table_data = query.all()

    # Данні для селектів
    form.company_id.choices = [('', '— Усі компанії —')] + [
        (c.id, c.name) for c in Company.query.order_by(Company.name).all()
    ]
    form.culture_id.choices = [('', '— Усі культури —')] + [
        (c.id, c.name) for c in Culture.query.order_by(Culture.name).all()
    ]
    form.product_id.choices = [('', '— Усі продукти —')] + [
        (p.id, p.name) for p in Product.query.order_by(Product.name).all()
    ]

    return render_template(
        'needs/summary.html',
        form=form,
        table_data=table_data
    )
