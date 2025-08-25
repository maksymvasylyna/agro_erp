from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from datetime import datetime
from io import BytesIO
import re
from sqlalchemy import func, distinct
from sqlalchemy.orm import joinedload, selectinload
from extensions import db
from .models import PayerAllocation
from .forms import AllocationFilterForm, BulkAssignForm
from modules.reference.payers.models import Payer
from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from .services import sync_from_plans  # синхронізація з планів

bp = Blueprint(
    "payer_allocation",
    __name__,
    url_prefix="/purchases/payer-allocation",
    template_folder="templates",
)

# ----------------------- ХЕЛПЕРИ -----------------------

def _pick_id(x):
    """Повертає .id для QuerySelectField або саме значення для SelectField(coerce=int)."""
    return getattr(x, "id", x) if x else None

def _unit_text(u):
    return (
        getattr(u, "short_name", None)
        or getattr(u, "symbol", None)
        or getattr(u, "name", None)
        or ""
    )

# ----------------------- ОСНОВНІ РОУТИ -----------------------

@bp.route("/", methods=["GET"])
def index():
    form = AllocationFilterForm(request.args)
    bulk_form = BulkAssignForm()

    company_id = _pick_id(form.company.data)
    product_id = _pick_id(form.product.data)
    manufacturer_id = _pick_id(form.manufacturer.data)
    payer_id = _pick_id(form.payer.data)

    q = (
        PayerAllocation.query
        .filter(PayerAllocation.status == "active")
        .options(
            selectinload(PayerAllocation.company),
            selectinload(PayerAllocation.field),
            selectinload(PayerAllocation.product),
            selectinload(PayerAllocation.manufacturer),
            selectinload(PayerAllocation.unit),
            selectinload(PayerAllocation.payer),
        )
        .order_by(
            PayerAllocation.company_id,
            PayerAllocation.field_id,
            PayerAllocation.product_id,
        )
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

    # Первинний автосинк лише коли ФІЛЬТРИ НЕ ЗАДАНО, щоб уникнути петлі редіректів.
    if not rows and not any([company_id, product_id, manufacturer_id, payer_id]):
        stats = sync_from_plans()
        if stats.get("added") or stats.get("updated"):
            flash(
                f"Виконано первинний імпорт з планів: додано {stats.get('added', 0)}, змінено {stats.get('updated', 0)}.",
                "info",
            )
            return redirect(url_for("payer_allocation.index", **request.args))

    # для селекторів платника в таблиці
    payers = Payer.query.order_by(Payer.name).all()

    return render_template(
        "payer_allocation/index.html",
        form=form,
        bulk_form=bulk_form,
        rows=rows,
        payers=payers,
        title="Розподіл між Платниками",
        header="💳 Розподіл між Платниками",
    )

@bp.route("/sync", methods=["POST"])
def sync():
    """Ручне оновлення з планів (upsert активних рядків, збереження payer_id)."""
    stats = sync_from_plans()
    flash(
        f"Оновлено з планів: додано {stats.get('added', 0)}, змінено {stats.get('updated', 0)}, "
        f"позначено застарілими {stats.get('marked_stale', 0)}. Активних: {stats.get('total_active', 0)}.",
        "success",
    )
    return redirect(url_for("payer_allocation.index"))

@bp.route("/bulk-assign", methods=["POST"])
def bulk_assign():
    # Прив'язуємо форму до POST-даних
    form = BulkAssignForm(request.form)

    ids_raw = (request.form.get("ids") or "").strip()
    if not ids_raw:
        flash("Не обрано жодного рядка.", "warning")
        return redirect(url_for("payer_allocation.index"))

    # Витягнемо лише числа, унікалізуємо, збережемо порядок появи
    ids_list = [int(x) for x in re.findall(r"\d+", ids_raw)]
    seen = set()
    ids = [x for x in ids_list if not (x in seen or seen.add(x))]

    if not ids:
        flash("Список обраних порожній.", "warning")
        return redirect(url_for("payer_allocation.index"))

    payer = form.payer.data  # QuerySelectField -> об'єкт; SelectField(coerce=int) -> int
    if not payer:
        flash("Оберіть платника.", "warning")
        return redirect(url_for("payer_allocation.index"))

    payer_id = getattr(payer, "id", payer)

    count = (
        PayerAllocation.query.filter(PayerAllocation.id.in_(ids))
        .update(
            {
                PayerAllocation.payer_id: payer_id,
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
    raw_pid = request.form.get("payer_id")

    if raw_pid is None:
        flash("Не обрано платника.", "warning")
        return redirect(url_for("payer_allocation.index"))

    raw_pid = raw_pid.strip()
    if raw_pid == "":  # очистити
        row.payer_id = None
        row.assigned_at = None
        db.session.commit()
        flash("Платника очищено.", "success")
        return redirect(url_for("payer_allocation.index"))

    try:
        pid = int(raw_pid)
    except ValueError:
        flash("Невірний платник.", "warning")
        return redirect(url_for("payer_allocation.index"))

    payer = Payer.query.get(pid)
    if not payer:
        flash("Невірний платник.", "warning")
        return redirect(url_for("payer_allocation.index"))

    row.payer_id = payer.id
    row.assigned_at = datetime.utcnow()
    db.session.commit()
    flash("Змінено платника.", "success")
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
            selectinload(PayerAllocation.company),
            selectinload(PayerAllocation.field),
            selectinload(PayerAllocation.product),
            selectinload(PayerAllocation.manufacturer),
            selectinload(PayerAllocation.unit),
            selectinload(PayerAllocation.payer),
        )
        .order_by(
            PayerAllocation.company_id,
            PayerAllocation.field_id,
            PayerAllocation.product_id
        )
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
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # Реєстрація шрифту для кирилиці
    font_path = os.path.join(current_app.root_path, 'static', 'fonts', 'DejaVuSans.ttf')
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('DejaVu', font_path))
        title_style = ParagraphStyle(name='DejaVuTitle', fontName='DejaVu', fontSize=16, leading=20)
        cell_font = 'DejaVu'
    else:
        title_style = ParagraphStyle(name='BaseTitle', fontSize=16, leading=20)
        cell_font = 'Helvetica'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Payer Allocation Export")
    elements = []

    subtitle = []
    if company_id:     subtitle.append(f"Компанія #{company_id}")
    if product_id:     subtitle.append(f"Продукт #{product_id}")
    if manufacturer_id:subtitle.append(f"Виробник #{manufacturer_id}")
    if payer_id:       subtitle.append(f"Платник #{payer_id}")
    sub = (" | ".join(subtitle)) if subtitle else "Усі записи"
    when = datetime.now().strftime("%Y-%m-%d %H:%M")

    elements.append(Paragraph("Розподіл між Платниками — експорт", title_style))
    elements.append(Paragraph(f"<font size=9>{sub} • {when}</font>", ParagraphStyle(name='Sub', fontName=cell_font, fontSize=9, leading=12)))
    elements.append(Spacer(1, 10))

    data = [["Підприємство", "Поле", "Продукт", "Виробник", "Кількість", "Одиниця", "Покупець"]]
    for r in rows:
        company_name = r.company.name if r.company else "—"
        field_name   = r.field.name if r.field else "—"
        product_name = r.product.name if r.product else "—"
        manuf_name   = r.manufacturer.name if r.manufacturer else "—"
        qty_text     = f"{r.qty:.2f}" if getattr(r, "qty", None) is not None else "—"
        unit_text    = _unit_text(r.unit) if r.unit else "—"
        payer_name   = r.payer.name if r.payer else "—"

        data.append([company_name, field_name, product_name, manuf_name, qty_text, unit_text, payer_name])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), cell_font),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="payer_allocation.pdf", mimetype="application/pdf")

# ----------------------- АУДИТ -----------------------

@bp.route("/audit", methods=["GET"])
def audit():
    """
    Аудит розподілів платників:
    - фільтри: field_id, payer_id
    - конфлікти в межах поля (продукт призначено різним платникам)
    - сироти (field_id IS NULL)
    - реєстр призначень
    - зведення (за платником у полі / за полем у платника)
    """
    field_id = request.args.get("field_id", type=int)
    payer_id = request.args.get("payer_id", type=int)

    # селект-опції
    fields = Field.query.order_by(Field.name).all()
    payers = Payer.query.order_by(Payer.name).all()

    # Базовий реєстр призначень
    alloc_q = (
        db.session.query(
            PayerAllocation.id.label("pa_id"),
            Field.id.label("field_id"), Field.name.label("field_name"),
            Product.id.label("product_id"), Product.name.label("product_name"),
            Payer.id.label("payer_id"), Payer.name.label("payer_name"),
        )
        .outerjoin(Field, Field.id == PayerAllocation.field_id)
        .join(Product, Product.id == PayerAllocation.product_id)
        .join(Payer, Payer.id == PayerAllocation.payer_id)
    )
    if field_id:
        alloc_q = alloc_q.filter(PayerAllocation.field_id == field_id)
    if payer_id:
        alloc_q = alloc_q.filter(PayerAllocation.payer_id == payer_id)

    allocations = alloc_q.order_by(
        func.coalesce(Field.name, func.cast(PayerAllocation.field_id, db.Integer)).asc(),
        Product.name.asc(),
        Payer.name.asc()
    ).all()

    # Конфлікти (лише якщо обрано поле)
    conflicts = []
    if field_id:
        conflict_heads = (
            db.session.query(
                Product.id.label("product_id"),
                Product.name.label("product_name"),
                func.count(distinct(PayerAllocation.payer_id)).label("payers_cnt"),
            )
            .join(Product, Product.id == PayerAllocation.product_id)
            .filter(PayerAllocation.field_id == field_id)
            .group_by(Product.id, Product.name)
            .having(func.count(distinct(PayerAllocation.payer_id)) > 1)
            .order_by(Product.name.asc())
            .all()
        )
        for row in conflict_heads:
            payer_names = (
                db.session.query(Payer.name)
                .join(Payer, Payer.id == PayerAllocation.payer_id)
                .filter(
                    PayerAllocation.field_id == field_id,
                    PayerAllocation.product_id == row.product_id
                )
                .distinct()
                .order_by(Payer.name.asc())
                .all()
            )
            conflicts.append({
                "product_id": row.product_id,
                "product_name": row.product_name,
                "payers_cnt": int(row.payers_cnt),
                "payers": [n for (n,) in payer_names],
            })

    # «Сироти» (рядки без прив'язки до поля) — показуємо, якщо не обрано field_id
    orphans = []
    if not field_id:
        orphans = (
            db.session.query(
                PayerAllocation.id.label("pa_id"),
                Product.name.label("product_name"),
                Payer.name.label("payer_name"),
            )
            .join(Product, Product.id == PayerAllocation.product_id)
            .join(Payer, Payer.id == PayerAllocation.payer_id)
            .filter(PayerAllocation.field_id.is_(None))
            .order_by(PayerAllocation.id.desc())
            .limit(200)
            .all()
        )

    # Зведення
    summary_by_payer = []
    if field_id:
        summary_by_payer = (
            db.session.query(
                Payer.name.label("payer_name"),
                func.count().label("allocs"),
                func.count(distinct(PayerAllocation.product_id)).label("products_cnt"),
            )
            .join(Payer, Payer.id == PayerAllocation.payer_id)
            .filter(PayerAllocation.field_id == field_id)
            .group_by(Payer.name)
            .order_by(Payer.name.asc())
            .all()
        )

    summary_by_field = []
    if payer_id:
        summary_by_field = (
            db.session.query(
                Field.name.label("field_name"),
                func.count().label("allocs"),
                func.count(distinct(PayerAllocation.product_id)).label("products_cnt"),
            )
            .join(Field, Field.id == PayerAllocation.field_id)
            .filter(PayerAllocation.payer_id == payer_id)
            .group_by(Field.name)
            .order_by(Field.name.asc())
            .all()
        )

    return render_template(
        "payer_allocation/audit.html",
        fields=fields,
        payers=payers,
        field_id=field_id,
        payer_id=payer_id,
        allocations=allocations,
        conflicts=conflicts,
        orphans=orphans,
        summary_by_payer=summary_by_payer,
        summary_by_field=summary_by_field,
    )
@bp.post("/audit/clear")
def audit_clear():
    """
    Очищення реєстру призначень зі сторінки аудиту.
    Параметри:
      action = 'delete' | 'unassign'   (за замовчуванням 'delete')
      scope  = 'filtered' | 'orphans' | 'all'  (за замовчуванням 'filtered')
      field_id, payer_id — для scope='filtered'
    """
    action   = (request.form.get("action") or "delete").strip().lower()
    scope    = (request.form.get("scope")  or "filtered").strip().lower()
    field_id = request.form.get("field_id", type=int)
    payer_id = request.form.get("payer_id", type=int)

    # Базовий запит
    q = PayerAllocation.query

    if scope == "orphans":
        q = q.filter(PayerAllocation.field_id.is_(None))
        scope_text = "сироти (без поля)"
    elif scope == "all":
        scope_text = "усі записи"
    else:  # 'filtered'
        if not field_id and not payer_id:
            flash("Щоб очистити за фільтром, оберіть Поле або Платника, або змініть режим на «Сироти» / «Все».", "warning")
            return redirect(url_for("payer_allocation.audit"))
        if field_id:
            q = q.filter(PayerAllocation.field_id == field_id)
        if payer_id:
            q = q.filter(PayerAllocation.payer_id == payer_id)
        scope_text = "поточний фільтр"

    # Виконання дії
    if action == "unassign":
        # зняти платника, залишити рядки
        updated = q.update(
            {PayerAllocation.payer_id: None, PayerAllocation.assigned_at: None},
            synchronize_session=False,
        )
        db.session.commit()
        flash(f"Знято платника у {updated} рядках ({scope_text}).", "success")
    else:
        # фізичне видалення рядків
        deleted = q.delete(synchronize_session=False)
        db.session.commit()
        flash(f"Видалено {deleted} рядків ({scope_text}).", "success")

    # Назад на аудит з тими самими фільтрами
    return redirect(url_for("payer_allocation.audit", field_id=field_id, payer_id=payer_id))
