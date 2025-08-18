# modules/purchases/needs/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from modules.purchases.needs.services import get_summary
from modules.reference.products.models import Product
from modules.reference.cultures.models import Culture
from modules.reference.companies.models import Company

needs_bp = Blueprint(
    "needs",
    __name__,
    url_prefix="/purchases/needs",
    template_folder="templates",
)

@needs_bp.after_request
def _no_cache(resp):
    # Щоб зведення не залежало від кешу браузера/проксі
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

@needs_bp.route("/summary", methods=["GET"])
def summary():
    company_id = request.args.get("company_id", type=int)
    culture_id = request.args.get("culture_id", type=int)
    product_id = request.args.get("product_id", type=int)

    data = get_summary(company_id=company_id, culture_id=culture_id, product_id=product_id)

    companies = Company.query.order_by(Company.name.asc()).all()
    cultures  = Culture.query.order_by(Culture.name.asc()).all()
    products  = Product.query.order_by(Product.name.asc()).all()

    return render_template(
        "needs/summary.html",
        data=data,
        companies=companies,
        cultures=cultures,
        products=products,
        company_id=company_id,
        culture_id=culture_id,
        product_id=product_id,
        title="Зведена потреба",
        header="🧮 Зведена потреба (затверджені плани)",
    )

@needs_bp.route("/summary/sync", methods=["POST"])
def summary_sync():
    """
    Спеціальний ендпойнт для кнопки 'Оновити з планів'.
    Ми не тримаємо проміжних таблиць, тому просто робимо редірект на summary
    з переданими фільтрами (hidden inputs), і все рахується наново.
    """
    company_id = request.form.get("company_id", type=int)
    culture_id = request.form.get("culture_id", type=int)
    product_id = request.form.get("product_id", type=int)

    flash("Зведення оновлено з затверджених планів.", "success")
    return redirect(
        url_for(
            "needs.summary",
            company_id=company_id or "",
            culture_id=culture_id or "",
            product_id=product_id or "",
        )
    )
