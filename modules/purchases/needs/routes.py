from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from io import BytesIO
from sqlalchemy.orm import joinedload
from extensions import db

# Зведення (старе) залишаємо недоторканим для інших екранів
from modules.purchases.needs.services import get_summary

# Довідники
from modules.reference.products.models import Product
from modules.reference.cultures.models import Culture
from modules.reference.companies.models import Company
from modules.reference.units.models import Unit
from modules.reference.manufacturers.models import Manufacturer
from modules.reference.payers.models import Payer

# Проплати
from modules.purchases.payments.models import PaymentInbox

# Розподіл між платниками (НОВЕ джерело для заявки)
from modules.purchases.payer_allocation.models import PayerAllocation
from modules.purchases.payer_allocation.services import (
    get_consolidated_with_remaining,  # (company, product, payer, manufacturer, unit) + qty_remaining
    get_already_ordered_map,          # (company, product, payer) -> already
    reconcile_allocations_against_plans,  # авто-очистка "хвостів"
)

needs_bp = Blueprint(
    "needs",
    __name__,
    url_prefix="/purchases/needs",
    template_folder="templates",
)

# ---- helpers ----
def _attach_labels(rows):
    """
    rows: список dict із ключами company_id, product_id, manufacturer_id, unit_id
    Додає company_name, product_name, manufacturer_name, unit_name.
    """
    if not rows:
        return rows

    company_ids = {r.get("company_id") for r in rows if r.get("company_id")}
    product_ids = {r.get("product_id") for r in rows if r.get("product_id")}
    manufacturer_ids = {r.get("manufacturer_id") for r in rows if r.get("manufacturer_id")}
    unit_ids = {r.get("unit_id") for r in rows if r.get("unit_id")}

    companies = Company.query.filter(Company.id.in_(company_ids)).all() if company_ids else []
    products  = Product.query.filter(Product.id.in_(product_ids)).all() if product_ids else []
    mans      = Manufacturer.query.filter(Manufacturer.id.in_(manufacturer_ids)).all() if manufacturer_ids else []
    units     = Unit.query.filter(Unit.id.in_(unit_ids)).all() if unit_ids else []

    cmap = {c.id: c.name for c in companies}
    pmap = {p.id: p.name for p in products}
    mmap = {m.id: m.name for m in mans}
    umap = {u.id: u.name for u in units}

    for r in rows:
        r["company_name"]      = r.get("company_name")      or cmap.get(r.get("company_id"), "—")
        r["product_name"]      = r.get("product_name")      or pmap.get(r.get("product_id"), "—")
        r["manufacturer_name"] = r.get("manufacturer_name") or mmap.get(r.get("manufacturer_id"), "—")
        r["unit_name"]         = r.get("unit_name")         or umap.get(r.get("unit_id"), "—")
    return rows


def _product_package(prod: Product | None) -> str | None:
    """
    Тара береться з довідника Продукти. Пробуємо кілька варіантів полів/зв'язків.
    """
    if not prod:
        return None
    for attr in ("container", "package", "packaging", "package_name", "pack_name", "package_size", "pack_size", "tare", "tare_name"):
        val = getattr(prod, attr, None)
        if val:
            return str(val)
    rel = getattr(prod, "package", None)
    name = getattr(rel, "name", None) if rel is not None else None
    return str(name) if name else None


def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _attach_manufacturer_from_product(rows):
    """
    Для кожного елемента rows (dict) гарантує наявність:
      row["manufacturer_id"], row["manufacturer_name"]
    Дані беруться з Product.manufacturer_id → Manufacturer.name.
    """
    if not rows:
        return rows

    prod_ids = {r["product_id"] for r in rows if r.get("product_id")}
    if not prod_ids:
        return rows

    # product_id -> manufacturer_id
    products = Product.query.with_entities(Product.id, Product.manufacturer_id)\
                            .filter(Product.id.in_(prod_ids)).all()
    p2m = {p.id: p.manufacturer_id for p in products}

    man_ids = {mid for mid in p2m.values() if mid}
    manmap = {m.id: m.name for m in (Manufacturer.query.filter(Manufacturer.id.in_(man_ids)).all() if man_ids else [])}

    for r in rows:
        mid = r.get("manufacturer_id") or p2m.get(r.get("product_id"))
        r["manufacturer_id"] = mid
        r["manufacturer_name"] = r.get("manufacturer_name") or (manmap.get(mid, "—") if mid else "—")

    return rows


@needs_bp.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ---------- Зведення (як було) ----------

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


# ---------- ЗАЯВКА З КОНСОЛІДОВАНОГО РОЗПОДІЛУ ----------

@needs_bp.route("/request", methods=["GET"], endpoint="request_form")
def request_form():
    """
    Форма заявки: тепер список показується одразу.
    Фільтри (company_id / product_id / payer_id) — опціональні.
    Вибір позицій/сабміт дозволяємо лише коли задано company_id.
    """
    company_id = request.args.get("company_id", type=int)
    product_id = request.args.get("product_id", type=int)
    payer_id   = request.args.get("payer_id", type=int)

    # ── авто-очистка «хвостів» перед побудовою списку ───────────────────────────
    try:
        reconcile_allocations_against_plans(
            company_id=company_id,
            product_ids=[product_id] if product_id else None,
        )
    except Exception:
        # не валимо сторінку, якщо щось пішло не так
        pass
    # ────────────────────────────────────────────────────────────────────────────

    companies = Company.query.order_by(Company.name.asc()).all()
    products  = Product.query.order_by(Product.name.asc()).all()
    payers    = Payer.query.order_by(Payer.name.asc()).all()

    # Тягнемо консолідацію навіть без company_id (покаже всі підприємства)
    base = get_consolidated_with_remaining(
        company_id=company_id,
        product_id=product_id,
        payer_id=payer_id,
    )

    rows = []
    for r in base:
        rows.append({
            "company_id": r["company_id"],
            "company_name": r.get("company_name"),
            "product_id": r["product_id"],
            "product_name": r.get("product_name"),
            "manufacturer_id": r.get("manufacturer_id"),
            "manufacturer_name": r.get("manufacturer_name"),
            "unit_id": r.get("unit_id"),
            "unit_name": r.get("unit_name"),
            "package": r.get("package"),
            "payer_id": r.get("payer_id"),
            "payer_name": r.get("payer_name"),
            "available": r.get("qty_remaining"),
        })

    # Добиваємо відсутні ярлики/виробника з продукту
    rows = _attach_manufacturer_from_product(rows)
    rows = _attach_labels(rows)

    selection_enabled = bool(company_id)

    return render_template(
        "needs/request_form.html",
        companies=companies,
        products=products,
        payers=payers,
        company_id=company_id,
        product_id=product_id,
        payer_id=payer_id,
        rows=rows,
        selection_enabled=selection_enabled,
        title="Заявка на закупівлю",
        header="🧾 Заявка на закупівлю (консолідація з розподілу)",
    )


@needs_bp.route("/request/preview", methods=["POST"], endpoint="request_preview")
def request_preview():
    """
    Попередній перегляд для заявки з консолідованого розподілу.
    Очікується, що форма надсилає:
      - чекбокси name="selected" value="{product_id}::{payer_id}"
      - інпути кількості name="qty_{product_id}_{payer_id}"
    Виробник відображається як статичний текст і береться з Product.
    """
    company_id = request.form.get("company_id", type=int)
    product_id = request.form.get("product_id", type=int)
    payer_id   = request.form.get("payer_id", type=int)

    if not company_id:
        flash("Оберіть підприємство (споживача).", "warning")
        return redirect(url_for("needs.request_form"))

    # Базові консолідовані рядки з залишком
    base = get_consolidated_with_remaining(
        company_id=company_id,
        product_id=product_id,
        payer_id=payer_id,
    )
    # Індекс за (product_id, payer_id)
    idx = {(r["product_id"], r["payer_id"]): r for r in base}

    selected = request.form.getlist("selected")
    chosen = []

    for key in selected:
        try:
            prod_str, payer_str = key.split("::", 1)
            pid = int(prod_str)
            pay = _safe_int(payer_str, None)
        except Exception:
            continue

        # Очікуємо qty_{pid}_{pay}
        qty_key = f"qty_{pid}_{pay if pay is not None else 0}"
        qty = request.form.get(qty_key, type=float) or 0.0
        if qty <= 0:
            continue

        row = idx.get((pid, pay))
        product = Product.query.get(pid)

        if not row:
            # fallback: якщо фільтри змінилися між запитами
            mid = product.manufacturer_id if product else None
            mobj = Manufacturer.query.get(mid) if mid else None
            mname = mobj.name if mobj else "—"
            chosen.append({
                "product_id": pid,
                "product_name": product.name if product else f"#{pid}",
                "payer_id": pay,
                "payer_name": None,
                "company_id": company_id,
                "company_name": Company.query.get(company_id).name if company_id else None,
                "package": _product_package(product),
                "manufacturer_id": mid,
                "manufacturer_name": mname,
                "requested_qty": qty,
                "available_qty": 0.0,
            })
            continue

        available = float(row.get("qty_remaining") or row.get("available") or 0.0)
        eff_qty   = min(qty, available)  # не більше залишку

        # виробник тільки з продукту (стале значення)
        mid = product.manufacturer_id if product else None
        mobj = Manufacturer.query.get(mid) if mid else None
        mname = mobj.name if mobj else "—"

        chosen.append({
            "product_id": pid,
            "product_name": row.get("product_name") or (product.name if product else f"#{pid}"),
            "payer_id": pay,
            "payer_name": row.get("payer_name"),
            "company_id": company_id,
            "company_name": row.get("company_name"),
            "package": row.get("package") or _product_package(product),
            "manufacturer_id": mid,
            "manufacturer_name": mname,
            "requested_qty": eff_qty,
            "available_qty": available,
        })

    company = Company.query.get(company_id) if company_id else None

    # ВАЖЛИВО: не передаємо список manufacturers у шаблон — UI має показувати статичний текст
    return render_template(
        "needs/request_preview.html",
        company=company,
        items=chosen,
        title="Попередній перегляд заявки",
        header="🔍 Попередній перегляд заявки",
    )


@needs_bp.route("/request/submit", methods=["POST"], endpoint="request_submit")
def request_submit():
    """
    Сабміт заявки з консолідованого розподілу.
    Очікує масиви:
      item_product_id[], item_payer_id[], item_qty[]
    УВАГА: manufacturer_id форсується з Product і НЕ береться з форми.
    Тара — автоматично з продукту. Після сабміту повертаємося на форму.
    """
    company_id = request.form.get("company_id", type=int)
    if not company_id:
        flash("Не вказано підприємство (споживача).", "warning")
        return redirect(url_for("needs.request_form"))

    product_ids = request.form.getlist("item_product_id[]")
    payer_ids   = request.form.getlist("item_payer_id[]")
    qtys        = request.form.getlist("item_qty[]")

    if not product_ids:
        flash("Немає позицій для відправки.", "warning")
        return redirect(url_for("needs.request_form", company_id=company_id or ""))

    # Побудуємо мапи для антидублювання й обмеження за залишком
    totals_rows = get_consolidated_with_remaining(company_id=company_id)
    total_map = { (r["product_id"], r["payer_id"]): float(r.get("qty_total") or r.get("total_qty") or 0.0)
                  for r in totals_rows }

    already_map = get_already_ordered_map(company_id=company_id)  # очікується ключ (company, product, payer)

    # Пакетне підвантаження продуктів і виробників
    pids = { _safe_int(x) for x in product_ids if _safe_int(x) is not None }
    products = { p.id: p for p in (Product.query.filter(Product.id.in_(pids)).all() if pids else []) }
    man_ids = { p.manufacturer_id for p in products.values() if p and p.manufacturer_id }
    manmap = { m.id: m for m in (Manufacturer.query.filter(Manufacturer.id.in_(man_ids)).all() if man_ids else []) }

    items = []
    used_map = {}  # локально додане у цьому сабміті: (pid, pay) -> added_qty

    n = len(product_ids)
    for i in range(n):
        pid = _safe_int(product_ids[i])
        pay = _safe_int(payer_ids[i])
        try:
            qty = float(qtys[i] or 0)
        except Exception:
            qty = 0.0

        if not pid or qty <= 0:
            continue

        product = products.get(pid)
        package = _product_package(product)

        # межа: total - already - locally_added
        total     = total_map.get((pid, pay), 0.0)
        already   = already_map.get((company_id, pid, pay), 0.0)
        added     = used_map.get((pid, pay), 0.0)
        remaining = max(total - already - added, 0.0)

        eff_qty = min(qty, remaining)
        if eff_qty <= 0:
            continue

        # ВИРОБНИК: тільки з продукту (форсуємо незалежно від форми)
        mid = product.manufacturer_id if product else None
        m   = manmap.get(mid) if mid else None

        # ім'я платника (для зручності відображення)
        payer_name = None
        if pay:
            payer = Payer.query.get(pay)
            payer_name = payer.name if payer else None

        items.append({
            "product_id": pid,
            "product_name": product.name if product else f"#{pid}",
            "qty": eff_qty,
            "package": package,
            "manufacturer_id": mid,
            "manufacturer_name": (m.name if m else None) or "—",
            "company_id": company_id,
            "company_name": Company.query.get(company_id).name if company_id else None,
            "payer_id": pay,
            "payer_name": payer_name,
        })

        used_map[(pid, pay)] = added + eff_qty

    if not items:
        flash("Нічого не відправлено: перевірте кількості/залишок.", "warning")
        return redirect(url_for("needs.request_form", company_id=company_id or ""))

    inbox = PaymentInbox(
        company_id=company_id,
        status="submitted",
        items_json=items,
    )
    db.session.add(inbox)
    db.session.commit()

    flash("Заявку відправлено в «Проплати». Ви повернуті до форми створення.", "success")
    return redirect(url_for("needs.request_form", company_id=company_id or ""))
