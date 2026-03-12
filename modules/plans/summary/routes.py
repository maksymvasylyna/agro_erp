import os
from io import BytesIO

from flask import render_template, request, make_response, current_app
from sqlalchemy import func

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from extensions import db
from . import summary_bp

from modules.plans.models import Plan, Treatment
from modules.reference.fields.field_models import Field
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.products.models import Product
from modules.reference.units.models import Unit


def register_pdf_fonts():
    fonts_dir = os.path.join(current_app.root_path, 'static', 'fonts')
    regular_font_path = os.path.join(fonts_dir, 'DejaVuSans.ttf')

    try:
        pdfmetrics.getFont('DejaVuSans')
    except KeyError:
        pdfmetrics.registerFont(TTFont('DejaVuSans', regular_font_path))

    try:
        pdfmetrics.getFont('DejaVuSans-Bold')
    except KeyError:
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', regular_font_path))

def build_summary_query(selected_company=None, selected_culture=None, selected_product=None):
    query = (
        db.session.query(
            Company.name.label('company_name'),
            Culture.name.label('culture_name'),
            Product.name.label('product_name'),
            func.sum(Treatment.quantity).label('total_quantity'),
            Unit.name.label('unit_name')
        )
        .join(Plan, Treatment.plan_id == Plan.id)
        .join(Field, Plan.field_id == Field.id)
        .join(Company, Field.company_id == Company.id)
        .outerjoin(Culture, Field.culture_id == Culture.id)
        .join(Product, Treatment.product_id == Product.id)
        .join(Unit, Product.unit_id == Unit.id)
    )

    if selected_company:
        query = query.filter(Company.id == selected_company)

    if selected_culture:
        query = query.filter(Culture.id == selected_culture)

    if selected_product:
        query = query.filter(Product.id == selected_product)

    return query


@summary_bp.route('/')
def index():
    selected_company = request.args.get('company_id', type=int)
    selected_culture = request.args.get('culture_id', type=int)
    selected_product = request.args.get('product_id', type=int)

    companies = Company.query.order_by(Company.name).all()
    cultures = Culture.query.order_by(Culture.name).all()
    products = Product.query.order_by(Product.name).all()

    summary_rows = (
        build_summary_query(selected_company, selected_culture, selected_product)
        .group_by(
            Company.name,
            Culture.name,
            Product.name,
            Unit.name
        )
        .order_by(
            Company.name,
            Culture.name,
            Product.name
        )
        .all()
    )

    total_quantity = sum((row.total_quantity or 0) for row in summary_rows)
    units_in_result = sorted(set(row.unit_name for row in summary_rows if row.unit_name))

    if len(units_in_result) == 1:
        total_unit = units_in_result[0]
    elif len(units_in_result) > 1:
        total_unit = 'різні од.'
    else:
        total_unit = ''

    return render_template(
        'summary/index.html',
        summary_rows=summary_rows,
        companies=companies,
        cultures=cultures,
        products=products,
        selected_company=selected_company,
        selected_culture=selected_culture,
        selected_product=selected_product,
        total_quantity=total_quantity,
        total_unit=total_unit
    )


@summary_bp.route('/pdf')
def export_pdf():
    register_pdf_fonts()

    selected_company = request.args.get('company_id', type=int)
    selected_culture = request.args.get('culture_id', type=int)
    selected_product = request.args.get('product_id', type=int)

    summary_rows = (
        build_summary_query(selected_company, selected_culture, selected_product)
        .group_by(
            Company.name,
            Culture.name,
            Product.name,
            Unit.name
        )
        .order_by(
            Company.name,
            Culture.name,
            Product.name
        )
        .all()
    )

    total_quantity = sum((row.total_quantity or 0) for row in summary_rows)
    units_in_result = sorted(set(row.unit_name for row in summary_rows if row.unit_name))

    if len(units_in_result) == 1:
        total_unit = units_in_result[0]
    elif len(units_in_result) > 1:
        total_unit = 'різні од.'
    else:
        total_unit = ''

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=20
    )

    styles = getSampleStyleSheet()
    styles['Title'].fontName = 'DejaVuSans-Bold'
    styles['Heading2'].fontName = 'DejaVuSans-Bold'
    styles['Normal'].fontName = 'DejaVuSans'

    elements = []

    elements.append(Paragraph("Зведена таблиця по планах", styles['Title']))
    elements.append(Spacer(1, 12))

    table_data = [
        ['Підприємство', 'Культура', 'Продукт', 'Кількість', 'Одиниця']
    ]

    for row in summary_rows:
        table_data.append([
            row.company_name or '',
            row.culture_name or '-',
            row.product_name or '',
            f"{row.total_quantity or 0:.2f}",
            row.unit_name or ''
        ])

    if summary_rows:
        table_data.append([
            '',
            '',
            'Разом',
            f"{total_quantity:.2f}",
            total_unit
        ])
    else:
        table_data.append(['Немає даних', '', '', '', ''])

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[160, 130, 220, 110, 90]
    )

    last_row_index = len(table_data) - 1

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),

        ('BACKGROUND', (0, last_row_index), (-1, last_row_index), colors.HexColor('#fff3cd')),
        ('FONTNAME', (0, last_row_index), (-1, last_row_index), 'DejaVuSans-Bold'),

        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

        ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
        ('FONTNAME', (0, 1), (-1, last_row_index - 1), 'DejaVuSans'),

        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=plans_summary.pdf'
    return response