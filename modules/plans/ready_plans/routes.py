from flask import Blueprint, render_template, request
from modules.plans.models import Plan
from modules.reference.fields.models import Field
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from flask import Blueprint, render_template, redirect, url_for, flash, send_file
from extensions import db
from modules.plans.forms import PlanForm
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.products.models import Product
from sqlalchemy.orm import joinedload
from modules.plans.models import Plan, Treatment


ready_plans_bp = Blueprint(
    'ready_plans',
    __name__,
    url_prefix='/plans/ready',
    template_folder='templates'
)


@ready_plans_bp.route('/', endpoint='index')
def index():
    company_id = request.args.get('company_id', type=int)
    culture_id = request.args.get('culture_id', type=int)

    # 🔧 Тут додано is_approved=False
    plans_query = Plan.query.filter_by(status='готовий', is_approved=False)

    if company_id:
        plans_query = plans_query.join(Plan.field).filter(Field.company_id == company_id)

    if culture_id:
        plans_query = plans_query.join(Plan.field).filter(Field.culture_id == culture_id)

    plans = plans_query.order_by(Plan.created_at.desc()).all()

    companies = Company.query.order_by(Company.name).all()
    cultures = Culture.query.order_by(Culture.name).all()

    return render_template(
        'ready_plans/index.html',
        plans=plans,
        companies=companies,
        cultures=cultures
    )


@ready_plans_bp.route('/<int:plan_id>')
def view_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    return render_template('ready_plans/view.html', plan=plan)

from flask import Blueprint, render_template, redirect, url_for, flash

@ready_plans_bp.route('/delete/<int:plan_id>', methods=['POST'])
def delete_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    db.session.delete(plan)
    db.session.commit()
    flash(f'План #{plan.id} успішно видалено 🗑️', 'success')
    return redirect(url_for('ready_plans.index'))

@ready_plans_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
def edit_plan(plan_id):
    print('>>> edit_plan: ВИКЛИК МАРШРУТУ')

    plan = Plan.query.get_or_404(plan_id)
    form = PlanForm()

    # 🔹 Довідники
    treatment_types = TreatmentType.query.all()
    products = Product.query.options(joinedload(Product.manufacturer), joinedload(Product.unit)).all()

    # 🔹 Списки choices
    choices_treatment = [(t.id, t.name) for t in treatment_types]
    choices_product = [(p.id, p.name) for p in products]

    # 🔹 Дані для JavaScript
    products_data = [
        {
            'id': p.id,
            'name': p.name,
            'manufacturer': p.manufacturer.name if p.manufacturer else '',
            'unit': p.unit.name if p.unit else ''
        }
        for p in products
    ]

    # 🔸 POST — збереження змін
    if request.method == 'POST':
        # 🛠️ Встановити choices перед валідацією
        for subform in form.treatments:
            subform.treatment_type_id.choices = choices_treatment
            subform.product_id.choices = choices_product

        print('🟡 POST запит активний')
        print('request.form:', request.form)
        print('form.errors:', form.errors)
        
        if form.validate_on_submit():
            # 🧹 Видалити старі обробітки
            for old in plan.treatments:
                db.session.delete(old)
            db.session.flush()

            # ➕ Додати нові обробітки
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
            flash('План оновлено ✅', 'success')
            return redirect(url_for('ready_plans.view_plan', plan_id=plan.id))

        else:
            flash('Помилка при збереженні форми ❌', 'danger')

    # 🔸 GET — завантаження форми
    if request.method == 'GET':
        print('План знайдено:', plan)
        print('К-сть обробітків у плані:', len(plan.treatments))
        for t in plan.treatments:
            form_entry = {
                'treatment_type_id': t.treatment_type_id,
                'product_id': t.product_id,
                'rate': t.rate,
                'unit': t.unit,
                'manufacturer': t.manufacturer,
                'quantity': t.quantity
            }
            form.treatments.append_entry(form_entry)

    print('🟡 POST запит активний')
    print('request.form:', request.form)
    print('form.errors:', form.errors)
        

    # 🛠️ Встановити choices після append_entry (GET)
    for subform in form.treatments:
        subform.treatment_type_id.choices = choices_treatment
        subform.product_id.choices = choices_product

    # 🔎 Debug (опційно)
    print('--- DEBUG ---')
    print('Form treatments:', form.treatments.entries)
    for i, subform in enumerate(form.treatments.entries):
        print(f"Subform {i}:")
        print('  treatment_type_id choices:', subform.treatment_type_id.choices)
        print('  product_id choices:', subform.product_id.choices)
    print('--------------')

    return render_template(
        'ready_plans/edit.html',
        form=form,
        plan=plan,
        treatment_types=treatment_types,
        products_data=products_data
    )




@ready_plans_bp.route('/approve_plan/<int:plan_id>')
def approve_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)

    if not plan.is_approved:
        plan.is_approved = True
        db.session.commit()
        flash('План успішно затверджено ✅', 'success')
    else:
        flash('План вже був затверджений', 'info')

    return redirect(url_for('ready_plans.index'))

@ready_plans_bp.route('/bulk_approve', methods=['POST'])
def bulk_approve():
    plan_ids = request.form.getlist('plan_ids')
    
    if not plan_ids:
        flash("❗ Не обрано жодного плану для затвердження", "warning")
        return redirect(url_for('ready_plans.index'))

    plans = Plan.query.filter(Plan.id.in_(plan_ids), Plan.is_approved == False).all()

    for plan in plans:
        plan.is_approved = True

    db.session.commit()

    flash(f"✅ Затверджено {len(plans)} план(ів)", "success")
    return redirect(url_for('ready_plans.index'))

@ready_plans_bp.route('/export_pdf')
def export_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO
    import os

    from modules.plans.models import Plan
    from modules.reference.fields.models import Field

    # 🔤 Підключаємо шрифт
    font_path = os.path.join('static', 'fonts', 'DejaVuSans.ttf')
    pdfmetrics.registerFont(TTFont('DejaVu', font_path))

    # 🔧 Стилі
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='DejaVuTitle', fontName='DejaVu', fontSize=18, leading=22))
    styles.add(ParagraphStyle(name='DejaVuNormal', fontName='DejaVu', fontSize=10, leading=14))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # 📝 Заголовок
    elements.append(Paragraph("Готові плани (фільтровані)", styles['DejaVuTitle']))
    elements.append(Spacer(1, 12))

    # 🔽 Отримуємо фільтри
    company_id = request.args.get('company_id', type=int)
    culture_id = request.args.get('culture_id', type=int)

    plans_query = Plan.query.filter_by(status='готовий', is_approved=False)

    if company_id:
        plans_query = plans_query.join(Plan.field).filter(Field.company_id == company_id)

    if culture_id:
        plans_query = plans_query.join(Plan.field).filter(Field.culture_id == culture_id)

    plans = plans_query.order_by(Plan.created_at.desc()).all()

    # 📋 Таблиця
    data = [["ID", "Поле", "Площа", "Культура", "Підприємство", "Дата створення"]]
    for plan in plans:
        data.append([
            str(plan.id),
            plan.field.name,
            f"{plan.field.area} га",
            plan.field.culture.name if plan.field.culture else "—",
            plan.field.company.name if plan.field.company else "—",
            plan.created_at.strftime('%d.%m.%Y'),
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'DejaVu')
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="готові_плани.pdf", mimetype='application/pdf')



@ready_plans_bp.route('/<int:plan_id>/export_pdf')
def export_single_plan_pdf(plan_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from io import BytesIO
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from modules.plans.models import Plan

    plan = Plan.query.get_or_404(plan_id)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # 🔤 Реєстрація шрифту для підтримки української мови
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'static/fonts/DejaVuSans.ttf'))
    styles['Normal'].fontName = 'DejaVuSans'
    styles['Title'].fontName = 'DejaVuSans'

    # Заголовок
    elements.append(Paragraph(f"План для поля: {plan.field.name}", styles['Title']))
    elements.append(Spacer(1, 12))

    # Інформація про поле
    field_info = f"""
    Площа: {plan.field.area} га<br/>
    Культура: {plan.field.culture.name if plan.field.culture else '—'}<br/>
    Підприємство: {plan.field.company.name if plan.field.company else '—'}<br/>
    Дата створення: {plan.created_at.strftime('%d.%m.%Y')}
    """
    elements.append(Paragraph(field_info, styles['Normal']))
    elements.append(Spacer(1, 12))

    # Таблиця обробітків
    data = [["Вид обробітку", "Продукт", "Норма", "Одиниця", "Виробник", "Кількість"]]
    for t in plan.treatments:
        data.append([
            t.treatment_type.name if t.treatment_type else '—',
            t.product.name if t.product else '—',
            f"{t.rate}",
            t.unit or '—',
            t.manufacturer or '—',
            f"{t.quantity}",
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans')
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"План_поле_{plan.field.name}.pdf",
                     mimetype='application/pdf')
