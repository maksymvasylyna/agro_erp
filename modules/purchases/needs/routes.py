from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from io import BytesIO
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
    Кнопка 'Оновити з планів' — просто редірект на summary з тими ж фільтрами,
    все рахується напряму з затверджених планів.
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

@needs_bp.route("/summary/export_pdf", methods=["GET"])
def summary_export_pdf():
    """
    Експорт зведеної потреби у PDF для поточних фільтрів (company_id, culture_id, product_id).
    """
    company_id = request.args.get("company_id", type=int)
    culture_id = request.args.get("culture_id", type=int)
    product_id = request.args.get("product_id", type=int)

    data = get_summary(company_id=company_id, culture_id=culture_id, product_id=product_id)

    # ==== PDF (ReportLab) ====
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    font_path = os.path.join('static', 'fonts', 'DejaVuSans.ttf')
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('DejaVu', font_path))
        title_style = ParagraphStyle(name='DejaVuTitle', fontName='DejaVu', fontSize=16, leading=20)
        cell_font = 'DejaVu'
    else:
        title_style = ParagraphStyle(name='BaseTitle', fontSize=16, leading=20)
        cell_font = 'Helvetica'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    elements.append(Paragraph("Зведена потреба (затверджені плани) — експорт", title_style))
    elements.append(Spacer(1, 10))

    data_rows = [["Продукт", "Культура", "Підприємство", "Кількість"]]
    for r in data:
        data_rows.append([r["product_name"], r["culture_name"], r["company_name"], f'{r["qty"]:.3f}'])

    table = Table(data_rows, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), cell_font),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="needs_summary.pdf", mimetype="application/pdf")
