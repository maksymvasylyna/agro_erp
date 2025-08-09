from flask import Blueprint, render_template, request, redirect, url_for, flash
from .forms import PlanForm
from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.clusters.models import Cluster
from modules.reference.cultures.models import Culture
from modules.reference.companies.models import Company
from modules.reference.fields.field_models import Field
from modules.plans.models import Plan, Treatment
from extensions import db

bp = Blueprint(
    'new_plans',
    __name__,
    url_prefix='/new_plans',
    template_folder='templates'  # вказує, де шукати шаблони ВІДНОСНО цього модуля
)


@bp.route('/')
def index():
    return render_template('new_plans/index.html')

@bp.route('/select_cluster')
def select_cluster():
    clusters = Cluster.query.order_by(Cluster.name).all()
    return render_template('new_plans/select_cluster.html', clusters=clusters)

@bp.route('/select_company/<int:cluster_id>')
def select_company(cluster_id):
    companies = Company.query.filter_by(cluster_id=cluster_id).all()
    return render_template('new_plans/select_company.html', companies=companies, cluster_id=cluster_id)


@bp.route('/select_field/<int:cluster_id>/<int:company_id>')
def select_field(cluster_id, company_id):
    company = Company.query.get_or_404(company_id)

    # Поля, які вже мають план
    used_field_ids = db.session.query(Plan.field_id).distinct()

    # Поля цієї компанії, які ще не використовувались у планах
    fields = Field.query.filter(
        Field.company_id == company_id,
        ~Field.id.in_(used_field_ids)
    ).order_by(Field.name).all()

    return render_template(
        'new_plans/select_field.html',
        company=company,
        cluster_id=cluster_id,
        fields=fields
    )




@bp.route('/create/<int:field_id>', methods=['GET', 'POST'])
def create_plan(field_id):
    field = Field.query.get_or_404(field_id)
    form = PlanForm()

    from sqlalchemy.orm import joinedload
    treatment_types = TreatmentType.query.all()
    products = Product.query.options(joinedload(Product.manufacturer), joinedload(Product.unit)).all()

    choices_treatment = [(t.id, t.name) for t in treatment_types]
    choices_product = [(p.id, p.name) for p in products]

    for subform in form.treatments:
        subform.treatment_type_id.choices = choices_treatment
        subform.product_id.choices = choices_product

    if request.method == 'POST':
        if form.validate_on_submit():
            # Створити новий план
            plan = Plan(field_id=field.id)
            db.session.add(plan)
            db.session.flush()

            # Додати всі обробітки
            for subform in form.treatments.entries:
                treatment = Treatment(
                    plan_id=plan.id,
                    treatment_type_id=subform.treatment_type_id.data,
                    product_id=subform.product_id.data,
                    rate=subform.rate.data,
                    unit=subform.unit.data,
                    manufacturer=subform.manufacturer.data,
                    quantity=subform.quantity.data
                )
                db.session.add(treatment)

            db.session.commit()
            flash('План збережено ✅', 'success')
            return redirect(url_for('new_plans.index'))
        else:
            flash('❌ Форма не пройшла валідацію', 'danger')
            print(form.errors)

    # Додаткові змінні для шаблону
    company = field.company
    cluster = company.cluster if company else None

    return render_template(
    'new_plans/create_plan.html',
    form=form,
    field=field,
    cluster=cluster,
    company=company,
    treatment_types=treatment_types,
    products=products
)

@bp.route('/bulk_template/select_fields', methods=['GET', 'POST'])
def bulk_template_select_fields():
    selected_company_id = request.args.get('company_id', type=int)
    selected_culture_id = request.args.get('culture_id', type=int)

    companies = Company.query.order_by(Company.name).all()
    cultures = Culture.query.order_by(Culture.name).all()

    # Поля без планів
    used_field_ids = db.session.query(Plan.field_id).distinct()

    fields_query = Field.query.filter(~Field.id.in_(used_field_ids))

    if selected_company_id:
        fields_query = fields_query.filter(Field.company_id == selected_company_id)
    if selected_culture_id:
        fields_query = fields_query.filter(Field.culture_id == selected_culture_id)

    fields = fields_query.order_by(Field.name).all()

    if request.method == 'POST':
        selected_field_ids = request.form.getlist('field_ids')
        if not selected_field_ids:
            flash("Оберіть хоча б одне поле ❗", 'warning')
            return redirect(request.url)

        return redirect(url_for('new_plans.bulk_template_create', field_ids=','.join(selected_field_ids)))

    return render_template(
        'new_plans/bulk_template/select_fields.html',
        fields=fields,
        companies=companies,
        cultures=cultures,
        selected_company_id=selected_company_id,
        selected_culture_id=selected_culture_id
    )
@bp.route('/bulk_template/create', methods=['GET', 'POST'])
def bulk_template_create():
    from sqlalchemy.orm import joinedload

    # ✅ Отримуємо список полів
    field_ids = request.args.get('field_ids') or request.form.get('field_ids')
    if not field_ids:
        flash("Не передано поля ❌", "danger")
        return redirect(url_for('new_plans.bulk_template_select_fields'))

    field_ids = [int(f_id) for f_id in field_ids.split(',')]
    fields = Field.query.filter(Field.id.in_(field_ids)).all()

    form = PlanForm()

    treatment_types = TreatmentType.query.all()
    products = Product.query.options(joinedload(Product.manufacturer), joinedload(Product.unit)).all()

    choices_treatment = [(t.id, t.name) for t in treatment_types]
    choices_product = [(p.id, p.name) for p in products]

    for subform in form.treatments:
        subform.treatment_type_id.choices = choices_treatment
        subform.product_id.choices = choices_product

    if request.method == 'POST':
        for subform in form.treatments:
            subform.treatment_type_id.choices = choices_treatment
            subform.product_id.choices = choices_product

        if form.validate_on_submit():
            for field in fields:
                plan = Plan(field_id=field.id)
                db.session.add(plan)
                db.session.flush()

                for subform in form.treatments.entries:
                    quantity = subform.rate.data * field.area if subform.rate.data and field.area else 0
                    treatment = Treatment(
                        plan_id=plan.id,
                        treatment_type_id=subform.treatment_type_id.data,
                        product_id=subform.product_id.data,
                        rate=subform.rate.data,
                        unit=subform.unit.data,
                        manufacturer=subform.manufacturer.data,
                        quantity=round(quantity, 1)
                    )
                    db.session.add(treatment)

            db.session.commit()
            flash(f"Створено {len(fields)} планів за шаблоном ✅", "success")
            return redirect(url_for('new_plans.index'))

        else:
            flash("❌ Форма не пройшла валідацію", "danger")
            print(form.errors)

    return render_template(
        'new_plans/bulk_template/template_form.html',
        form=form,
        fields=fields,
        treatment_types=treatment_types,
        products=products,
        field_ids=','.join([str(f.id) for f in fields])
    )




# Обовʼязково — для підключення у register_blueprints.py
new_plans_bp = bp
