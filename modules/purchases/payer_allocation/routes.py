from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from datetime import datetime
from io import BytesIO
from sqlalchemy.orm import joinedload
from extensions import db
from .models import PayerAllocation
from .forms import AllocationFilterForm, BulkAssignForm
from modules.reference.payers.models import Payer
from .services import sync_from_plans  # синхронізація з планів

bp = Blueprint(
    "payer_allocation",
    __name__,
    url_prefix="/purchases/payer-allocation",
    template_folder="templates",
)

@bp.route("/", methods=["GET"])
def index():
    form = AllocationFilterForm(request.args)
    bulk_form = BulkAssignForm()

    q = PayerAllocation.query.filter(PayerAllocation.status == "active")

    if form.company.data:
        q = q.filter(PayerAllocation.company_id == form.company.data.id)
    if form.product.data:
        q = q.filter(PayerAllocation.product_id == form.product.data.id)
    if form.manufacturer.data:
        q = q.filter(PayerAllocation.manufacturer_id == form.manufacturer.data.id)
    if form.payer.data:
        q = q.filter(PayerAllocation.payer_id == form.payer.data.id)

    q = q.order_by(
        PayerAllocation.company_id,
        PayerAllocation.field_id,
        PayerAllocation.product_id
    )

    rows = q.all()

    # первинний автосинк: якщо порожньо — підтягнемо з планів один раз
    if not rows:
        stats = sync_from_plans()
        if stats["added"] or stats["updated"]:
            flash(
                f"Виконано первинний імпорт з планів: додано {stats['added']}, змінено {stats['updated']}.",
                "info"
            )
            return redirect(url_for("payer_allocation.index"))

    return render_template(
        "payer_allocation/index.html",
        form=form,
        bulk_form=bulk_form,
        rows=rows,
        title="Розподіл між Платниками",
        header="💳 Розподіл між Платниками",
    )

@bp.route("/sync", methods=["POST"])
def sync():
    """Ручне оновлення з планів (upsert активних рядків, збереження payer_id)."""
    stats = sync_from_plans()
    flash(
        f"Оновлено з планів: додано {stats['added']}, змінено {stats['updated']}, "
        f"позначено застарілими {stats['marked_stale']}. Активних: {stats['total_active']}.",
        "success"
    )
    return redirect(url_for("payer_allocation.index"))

@bp.route("/bulk-assign", methods=["POST"])
def bulk_assign():
    form = BulkAssignForm()
    ids_raw = request.form.get("ids", "").strip()
    if not ids_raw:
        flash("Не обрано жодного рядка.", "warning")
        return redirect(url_for("payer_allocation.index"))

    try:
        ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        flash("Список обраних порожній.", "warning")
        return redirect(url_for("payer_allocation.index"))

    payer = form.payer.data
    if not payer:
        flash("Оберіть платника.", "warning")
        return redirect(url_for("payer_allocation.index"))

    count = (
        PayerAllocation.query.filter(PayerAllocation.id.in_(ids))
        .update(
            {
                PayerAllocation.payer_id: payer.id,
                PayerAllocation.assigned_at: datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.session.commit()
    flash(f"Призначено платника для {count} рядків.", "success")
    return redirect(url_for("payer_allocation.index"))

@bp.route("/<int:row_id>/set-payer", methods=["POST"])
def set_payer(row_id):
    row = PayerAllocation.query.get_or_404(row_id)
    payer_id = request.form.get("payer_id")
    if payer_id is not None:
        if payer_id == "":  # очистити
            row.payer_id = None
            row.assigned_at = None
        else:
            payer = Payer.query.get(int(payer_id))
            if not payer:
                flash("Невірний платник.", "warning")
                return redirect(url_for("payer_allocation.index"))
            row.payer_id = payer.id
            row.assigned_at = datetime.utcnow()
        db.session.commit()
        flash("Змінено платника.", "success")
    else:
        flash("Не обрано платника.", "warning")
    return redirect(url_for("payer_allocation.index"))

@bp.route("/export_pdf", methods=["GET"])
def export_pdf():
    """
    Експорт поточного відфільтрованого списку у PDF.
    Очікує ті самі query params, що й index(): company, product, manufacturer, payer (ID).
    """
    # фільтри з query string
    company_id = request.args.get("company", type=int)
    product_id = request.args.get("product", type=int)
    manufacturer_id = request.args.get("manufacturer", type=int)
    payer_id = request.args.get("payer", type=int)

    q = (
        PayerAllocation.query
        .filter(PayerAllocation.status == "active")
        .options(
            joinedload(PayerAllocation.company),
            joinedload(PayerAllocation.field),
            joinedload(PayerAllocation.product),
            joinedload(PayerAllocation.manufacturer),
            joinedload(PayerAllocation.unit),
            joinedload(PayerAllocation.payer),
        )
        .order_by(PayerAllocation.company_id, PayerAllocation.field_id, PayerAllocation.product_id)
    )

    if company_id:
        q = q.filter(PayerAllocation.company_id == company_id)
    if product_id:
        q = q.filter(PayerAllocation.product_id == product_id)
    if manufacturer_id:
        q = q.filter(PayerAllocation.manufacturer_id == manufacturer_id)
    if payer_id:
        q = q.filter(PayerAllocation.payer_id == payer_id)

    rows = q.all()

    # ==== PDF побудова (ReportLab) ====
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # Реєстрація шрифту для кирилиці
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

    elements.append(Paragraph("Розподіл між Платниками — експорт", title_style))
    elements.append(Spacer(1, 10))

    # Таблиця
    data = [["Підприємство", "Поле", "Продукт", "Виробник", "Кількість", "Одиниця", "Покупець"]]
    for r in rows:
        data.append([
            r.company.name if r.company else "—",
            r.field.name if r.field else "—",
            r.product.name if r.product else "—",
            r.manufacturer.name if r.manufacturer else "—",
            f"{r.qty}",
            r.unit.name if r.unit else "—",
            r.payer.name if r.payer else "—",
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), cell_font),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),  # qty праворуч
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="payer_allocation.pdf", mimetype="application/pdf")
