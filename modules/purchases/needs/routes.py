# modules/purchases/needs/routes.py

from flask import Blueprint, render_template, request
from modules.purchases.needs.services import get_summary_data
from modules.purchases.needs.forms import NeedsFilterForm

needs_bp = Blueprint('needs', __name__, template_folder='templates')


@needs_bp.route('/purchases/needs/summary', methods=['GET'])
def summary_needs():
    form = NeedsFilterForm(request.args)

    company_id = form.company.data.id if form.company.data else None
    culture_id = form.culture.data.id if form.culture.data else None
    product_id = form.product.data.id if form.product.data else None

    table_data = get_summary_data(company_id, culture_id, product_id)

    return render_template(
        'purchases/needs/summary.html',
        form=form,
        summary_data=table_data
    )
