# modules/structure/fields_structure/routes.py

from flask import Blueprint, render_template, request
from modules.reference.fields.models import Field
from modules.structure.fields_structure.forms import FieldsStructureFilterForm

fields_structure_bp = Blueprint(
    'fields_structure',
    __name__,
    template_folder='templates'
)

@fields_structure_bp.route('/structure/fields')
def index():
    filter_form = FieldsStructureFilterForm(request.args)

    query = Field.query

    if filter_form.cluster.data:
        query = query.filter_by(cluster_id=filter_form.cluster.data.id)
    if filter_form.company.data:
        query = query.filter_by(company_id=filter_form.company.data.id)
    if filter_form.culture.data:
        query = query.filter_by(culture_id=filter_form.culture.data.id)

    fields = query.order_by(Field.name).all()

    # ✅ Підсумок площі
    total_area = sum(f.area or 0 for f in fields)

    print("🔍 Знайдено полів:", len(fields))
    print("✅ Сумарна площа:", total_area)
    for f in fields:
        print(f.id, f.name, f.area)

    return render_template(
        'fields_structure/index.html',
        filter_form=filter_form,
        items=fields,
        total_area=total_area
    )
