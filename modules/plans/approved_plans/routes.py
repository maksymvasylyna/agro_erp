
from extensions import db
from flask import abort, request, render_template, redirect, url_for, flash
from . import bp
from modules.plans.models import Plan, Treatment
from modules.plans.security import verify_plan_action
from modules.plans.season import context, current, plan_or_404
from modules.reference.fields.field_models import Field
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.products.models import Product

from sqlalchemy.orm import joinedload

@bp.route('/', endpoint='index')
def index():
    # ⏬ Отримуємо параметри з GET-запиту
    company_id = request.args.get('company_id', type=int)
    culture_id = request.args.get('culture_id', type=int)
    product_id = request.args.get('product_id', type=int)

    # ⏬ Базовий запит: лише затверджені плани
    plans_query = Plan.query.filter_by(is_approved=True, season_id=current().id).options(
        joinedload(Plan.field),
        joinedload(Plan.treatments).joinedload(Treatment.product)
    )

    # 🔍 Фільтрація за компанією (через поле)
    if company_id:
        plans_query = plans_query.join(Plan.field).filter(Field.company_id == company_id)

    # 🔍 Фільтрація за культурою
    if culture_id:
        plans_query = plans_query.join(Plan.field).filter(Field.culture_id == culture_id)


    plans = plans_query.order_by(Plan.created_at.desc()).all()

    companies = Company.query.order_by(Company.name).all()
    cultures = Culture.query.order_by(Culture.name).all()
    products = Product.query.order_by(Product.name).all()

    return render_template(
        'approved_plans/index.html',
        plans=plans,
        companies=companies,
        cultures=cultures,
        selected_company=company_id,
        selected_culture=culture_id, **context()
    )
@bp.post('/unlock/<int:plan_id>')
def unlock_plan(plan_id):
    verify_plan_action(admin=True)
    plan = plan_or_404(plan_id)

    if plan.is_approved:
        plan.is_approved = False
        db.session.commit()
        flash('🔓 План знову доступний для редагування', 'warning')
    else:
        flash('План уже не затверджений', 'info')

    return redirect(url_for('approved_plans.index'))

@bp.route('/<int:plan_id>')
def view_plan(plan_id):
    plan = plan_or_404(plan_id)
    field = plan.field
    treatments = plan.treatments

    return render_template(
        'approved_plans/view_plan.html',
        plan=plan,
        field=field,
        treatments=treatments
    )

@bp.post('/<int:plan_id>/unapprove')
def unapprove_plan(plan_id):
    verify_plan_action(admin=True)
    plan = plan_or_404(plan_id)
    if not plan.is_approved:
        abort(409, description="План уже не затверджений.")
    plan.is_approved = False
    db.session.commit()
    flash(f'План №{plan.id} знову перенесено до "Готових" ⬅️', 'info')
    return redirect(url_for('approved_plans.index'))

@bp.route('/export_pdf')
def export_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from io import BytesIO
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    from flask import send_file, request
    from modules.plans.models import Plan, Treatment
    from modules.reference.fields.field_models import Field

    # ✅ Параметри фільтрації
    company_id = request.args.get('company_id', type=int)
    culture_id = request.args.get('culture_id', type=int)

    # 🟩 Фільтрація затверджених планів
    plans_query = Plan.query.filter_by(status='готовий', is_approved=True, season_id=current().id)

    if company_id:
        plans_query = plans_query.join(Plan.field).filter(Field.company_id == company_id)

    if culture_id:
        plans_query = plans_query.join(Plan.field).filter(Field.culture_id == culture_id)

    plans = plans_query.all()

    # 🧾 Створення PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # 🔤 Додати підтримку української мови
    FONT_PATH = os.path.join("static", "fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
    styles["Normal"].fontName = "DejaVu"
    styles["Title"].fontName = "DejaVu"

    elements.append(Paragraph("Затверджені плани", styles['Title']))
    elements.append(Spacer(1, 12))

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
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="затверджені_плани.pdf",
        mimetype='application/pdf'
    )

@bp.route('/<int:plan_id>/export_pdf')
def export_plan_pdf(plan_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO
    import os
    from flask import send_file
    from modules.plans.models import Plan, Treatment

    plan = plan_or_404(plan_id)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # 🔤 Підключаємо український шрифт
    FONT_PATH = os.path.join("static", "fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
    styles["Normal"].fontName = "DejaVu"
    styles["Title"].fontName = "DejaVu"

    elements.append(Paragraph(f"План №{plan.id} — {plan.field.name}", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Площа: {plan.field.area} га", styles["Normal"]))
    elements.append(Paragraph(f"Культура: {plan.field.culture.name if plan.field.culture else '—'}", styles["Normal"]))
    elements.append(Paragraph(f"Підприємство: {plan.field.company.name if plan.field.company else '—'}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Таблиця обробітків
    data = [["Вид обробітку", "Продукт", "Норма", "Одиниця", "Виробник", "Кількість"]]

    for t in plan.treatments:
        data.append([
            t.treatment_type.name if t.treatment_type else "—",
            t.product.name if t.product else "—",
            f"{t.rate:.2f}",
            t.unit or "—",
            t.manufacturer or "—",
            f"{t.quantity:.1f}"
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"план_{plan.id}.pdf",
        mimetype='application/pdf'
    )
