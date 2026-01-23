# modules/requests/shipments/routes.py
from datetime import datetime
import json
from markupsafe import Markup
from flask import render_template, request, url_for, redirect, flash
from . import shipments_requests_bp
from .forms import FilterForm
from .services import get_stock_balances
from .models import ShipmentRequest, ShipmentRequestItem
from extensions import db

# Довідники для фолбеків
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from modules.reference.companies.models import Company
from modules.reference.payers.models import Payer
from modules.reference.manufacturers.models import Manufacturer

# 🔧 для агрегацій
from sqlalchemy import func
from collections import defaultdict

# -------------------- бізнес-налаштування --------------------
# Округлення до кратності тари під час preview (та, за потреби, на submit):
# "ceil" | "floor" | "nearest" | "error" (error = не коригуємо, вимагаємо вручну)
ROUND_TO_PACKAGE_MODE = "ceil"

# Які статуси вважаємо «зайняли склад» при розрахунку вже зарезервованих обсягів
RESERVE_STATUSES = ("draft", "submitted", "approved")

# Резервувати покомпанійно+продукт+платник (True) або без урахування платника (False)
RESERVE_BY_PAYER = True
# -------------------------------------------------------------

# -------------------- helpers --------------------
def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_float(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _noneify(v):
    """Перетворити рядки 'None'/'none'/'null' і '' на None."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "None", "none", "null", "Null"):
            return None
    return v


def _has_ref(r: dict, id_key: str, name_key: str) -> bool:
    """Є валідне посилання, якщо або є числовий id, або непорожня назва."""
    id_ok = _as_int(r.get(id_key)) is not None
    name_ok = bool((r.get(name_key) or "").strip())
    return id_ok or name_ok


def _row_is_valid(r: dict) -> bool:
    return (
        _has_ref(r, "product_id", "product_name")
        and _has_ref(r, "unit_id", "unit_text")
        and _to_float(r.get("qty_requested")) > 0
    )


def _round_to_pack(qty: float, pack: float, mode: str) -> float:
    """Повертає qty, приведену до кратної pack згідно mode."""
    if not pack or pack <= 0:
        return qty
    import math
    n = qty / pack
    if mode == "ceil":
        k = math.ceil(n)
    elif mode == "floor":
        k = math.floor(n)
    elif mode == "nearest":
        k = round(n)
    elif mode == "error":
        k = n  # не чіпаємо; перевіримо окремо
    else:
        k = math.ceil(n)
    return max(0.0, k * pack)


def _is_multiple(qty: float, pack: float, eps: float = 1e-9) -> bool:
    if not pack or pack <= 0:
        return True
    import math
    if pack == 0:
        return True
    # модуль частки від ділення на pack має бути ~0
    frac = (qty / pack) % 1
    return math.isclose(frac, 0.0, abs_tol=eps)


def _row_key(company_id, product_id, payer_id):
    if RESERVE_BY_PAYER:
        return (company_id or 0, product_id or 0, payer_id or 0)
    return (company_id or 0, product_id or 0, 0)


def _build_reserved_map():
    """
    Резерви за вже створеними заявками (draft/submitted/approved), сумарно по ключу.
    """
    q = (
        db.session.query(
            ShipmentRequestItem.consumer_company_id.label("company_id"),
            ShipmentRequestItem.product_id.label("product_id"),
            ShipmentRequestItem.payer_id.label("payer_id"),
            func.sum(ShipmentRequestItem.qty_requested).label("qty")
        )
        .join(ShipmentRequest, ShipmentRequestItem.request_id == ShipmentRequest.id)
        .filter(ShipmentRequest.status.in_(RESERVE_STATUSES))
        .group_by(ShipmentRequestItem.consumer_company_id,
                  ShipmentRequestItem.product_id,
                  ShipmentRequestItem.payer_id)
    )
    reserved = defaultdict(float)
    for row in q:
        key = _row_key(row.company_id, row.product_id, row.payer_id)
        reserved[key] += float(row.qty or 0.0)
    return reserved
# -------------------------------------------------


@shipments_requests_bp.route("/requests/shipments", methods=["GET", "POST"])
def index():
    """
    ЄДИНА сторінка:
    - GET: показуємо всі залишки (без фільтрів).
    - POST (фільтр): показуємо відфільтровані залишки.
    У будь-якому випадку нижче форми показується таблиця з можливістю вибору та переходу в preview_new.
    """
    form = FilterForm()

    # Зчитуємо вибір із POST (натиснули "Фільтрувати") або з query args (для збереження стану при refresh)
    if form.validate_on_submit():
        company_id = form.company.data.id if form.company.data else None
        product_id = form.product.data.id if form.product.data else None
    else:
        company_id = _as_int(request.args.get("company_id") or None)
        product_id = _as_int(request.args.get("product_id") or None)

    # balances: якщо фільтри порожні — вертаємо ВСІ в наявності
    balances = get_stock_balances(company_id=company_id, product_id=product_id) or []

    # Уніфікація ключів + поповнення одиниць/тари
    for r in balances:
        r["company_id"]        = r.get("company_id")
        r["company_name"]      = r.get("company_name") or r.get("company") or r.get("consumer_company_name") or ""

        r["payer_id"]          = r.get("payer_id")
        r["payer_name"]        = r.get("payer_name") or r.get("payer") or ""

        r["product_id"]        = r.get("product_id")
        r["product_name"]      = r.get("product_name") or r.get("product") or ""

        r["manufacturer_id"]   = r.get("manufacturer_id")
        r["manufacturer_name"] = r.get("manufacturer_name") or r.get("manufacturer") or ""

        r["unit_id"]           = r.get("unit_id") or r.get("uom_id")
        r["unit_text"]         = r.get("unit_text") or r.get("unit_name") or r.get("uom") or ""

        r["package_value"]     = r.get("package_value")
        r["package_text"]      = r.get("package_text") or r.get("pkg_text") or r.get("package") or ""

        if r.get("qty_available") is None:
            r["qty_available"] = r.get("qty") or r.get("quantity") or r.get("stock") or 0

    # Потрібно підтягнути одиниці з продукту?
    prod_ids_need_unit = {
        _as_int(r["product_id"])
        for r in balances
        if (not (r.get("unit_id") or r.get("unit_text"))) and r.get("product_id")
    }
    prod_ids_need_unit = {pid for pid in prod_ids_need_unit if pid is not None}

    prod_to_unit = {}
    unit_id_to_name = {}
    if prod_ids_need_unit:
        prods = Product.query.filter(Product.id.in_(prod_ids_need_unit)).all()
        for p in prods:
            uid = getattr(p, "unit_id", None)
            if not uid and getattr(p, "unit", None) and getattr(p.unit, "id", None):
                uid = p.unit.id
            if uid:
                prod_to_unit[p.id] = uid

        unit_ids = set(prod_to_unit.values())
        if unit_ids:
            units = Unit.query.filter(Unit.id.in_(unit_ids)).all()
            unit_id_to_name = {u.id: (u.name or u.short_name or "") for u in units}

    for r in balances:
        if not (r.get("unit_text") or ""):
            uid = _as_int(r.get("unit_id"))
            if uid is None:
                pid = _as_int(r.get("product_id"))
                if pid in prod_to_unit:
                    uid = prod_to_unit[pid]
                    r["unit_id"] = uid
            if uid and uid in unit_id_to_name:
                r["unit_text"] = unit_id_to_name[uid] or r.get("unit_text") or ""

        if not (r.get("package_text") or ""):
            try:
                pv = float(r.get("package_value")) if r.get("package_value") not in (None, "") else None
            except (TypeError, ValueError):
                pv = None
            if pv and (r.get("unit_text") or ""):
                r["package_text"] = f"{pv:g} {r['unit_text']}"

    # Пробуємо проставити значення у форму (щоб після POST лишилися вибрані)
    if company_id:
        form.company.data = Company.query.get(company_id)
    if product_id:
        form.product.data = Product.query.get(product_id)

    return render_template(
        "shipments/index.html",
        form=form,
        balances=balances,
        company_id=company_id,
        product_id=product_id,
    )


@shipments_requests_bp.route("/requests/shipments/preview_new", methods=["POST"])
def preview_new():
    """
    Приймаємо вибране, нормалізуємо дані, добудовуємо снапшоти,
    рахуємо allow/reserved, округлюємо до тари і повертаємо ТІЛЬКИ чисті dict з потрібними ключами.
    """
    picked = request.form.getlist("pick[]")
    if not picked:
        flash("Не обрано жодної позиції.", "warning")
        return redirect(url_for("shipments_requests.index"))

    rows = []
    for idx_str in picked:
        idx = _as_int(idx_str)
        if idx is None:
            continue
        key = f"rows[{idx}]"
        row = {
            # ids/числа беремо як сирі строки — нижче все одно приведемо типи
            "company_id": _noneify(request.form.get(f"{key}[company_id]")),
            "product_id": _noneify(request.form.get(f"{key}[product_id]")),
            "payer_id": _noneify(request.form.get(f"{key}[payer_id]")),
            "unit_id": _noneify(request.form.get(f"{key}[unit_id]")),
            "manufacturer_id": _noneify(request.form.get(f"{key}[manufacturer_id]")),
            "package_value": _noneify(request.form.get(f"{key}[package_value]")),
            "qty_available": _noneify(request.form.get(f"{key}[qty_available]")),
            "qty_requested": _noneify(request.form.get(f"{key}[qty_requested]")),
            # снапшоти
            "company_name": (request.form.get(f"{key}[company_name]") or "").strip(),
            "product_name": (request.form.get(f"{key}[product_name]") or "").strip(),
            "payer_name": (request.form.get(f"{key}[payer_name]") or "").strip(),
            "unit_text": (request.form.get(f"{key}[unit_text]") or "").strip(),
            "manufacturer_name": (request.form.get(f"{key}[manufacturer_name]") or "").strip(),
            "package_text": (request.form.get(f"{key}[package_text]") or "").strip(),
        }
        rows.append(row)

    # Добудова snapshot-імен із БД за id
    unit_ids  = { _as_int(r.get("unit_id")) for r in rows if _as_int(r.get("unit_id")) is not None }
    prod_ids  = { _as_int(r.get("product_id")) for r in rows if _as_int(r.get("product_id")) is not None }
    comp_ids  = { _as_int(r.get("company_id")) for r in rows if _as_int(r.get("company_id")) is not None }
    payr_ids  = { _as_int(r.get("payer_id")) for r in rows if _as_int(r.get("payer_id")) is not None }
    manuf_ids = { _as_int(r.get("manufacturer_id")) for r in rows if _as_int(r.get("manufacturer_id")) is not None }

    units_map = {u.id: (u.name or u.short_name or "") for u in Unit.query.filter(Unit.id.in_(unit_ids)).all()} if unit_ids else {}
    prods_map = {p.id: (p.name or "") for p in Product.query.filter(Product.id.in_(prod_ids)).all()} if prod_ids else {}
    comps_map = {c.id: (c.name or "") for c in Company.query.filter(Company.id.in_(comp_ids)).all()} if comp_ids else {}
    pays_map  = {p.id: (p.name or "") for p in Payer.query.filter(Payer.id.in_(payr_ids)).all()} if payr_ids else {}
    mans_map  = {m.id: (m.name or "") for m in Manufacturer.query.filter(Manufacturer.id.in_(manuf_ids)).all()} if manuf_ids else {}

    for r in rows:
        if not r["unit_text"]:
            uid = _as_int(r.get("unit_id"))
            if uid in units_map: r["unit_text"] = units_map[uid]
        if not r["product_name"]:
            pid = _as_int(r.get("product_id"))
            if pid in prods_map: r["product_name"] = prods_map[pid]
        if not r["company_name"]:
            cid = _as_int(r.get("company_id"))
            if cid in comps_map: r["company_name"] = comps_map[cid]
        if not r["payer_name"]:
            pid = _as_int(r.get("payer_id"))
            if pid in pays_map: r["payer_name"] = pays_map[pid]
        if not r["manufacturer_name"]:
            mid = _as_int(r.get("manufacturer_id"))
            if mid in mans_map: r["manufacturer_name"] = mans_map[mid]

        if not r["package_text"]:
            pv = _as_float(r.get("package_value"), default=None)
            if pv and r["unit_text"]:
                r["package_text"] = f"{pv:g} {r['unit_text']}"

    # Резерви з БД
    reserved_map = _build_reserved_map()

    adjusted = []
    warnings = []

    for r in rows:
        # уніфікація типів
        qty_av = _as_float(r.get("qty_available"), default=0.0) or 0.0
        qty_req = _as_float(r.get("qty_requested"), default=0.0) or 0.0
        pack    = _as_float(r.get("package_value"), default=0.0) or 0.0

        company_id_i = _as_int(r.get("company_id"))
        product_id_i = _as_int(r.get("product_id"))
        payer_id_i   = _as_int(r.get("payer_id"))

        # ключ для резервів
        already_reserved = reserved_map.get(_row_key(company_id_i, product_id_i, payer_id_i), 0.0)
        allow = max(0.0, qty_av - already_reserved)

        original_qty = qty_req

        # 1) обмеження allow
        if qty_req > allow > 0:
            qty_req = allow
            warnings.append(
                f"«{r.get('product_name') or product_id_i}» по «{r.get('company_name') or company_id_i}» "
                f"обмежено до {allow:g} (з урахуванням існуючих заявок)."
            )
        elif allow <= 0:
            qty_req = 0.0
            warnings.append(
                f"«{r.get('product_name') or product_id_i}» по «{r.get('company_name') or company_id_i}» "
                f"зараз недоступний: усе зарезервовано."
            )

        # 2) кратність тари
        if pack and qty_req > 0:
            if ROUND_TO_PACKAGE_MODE == "error":
                if not _is_multiple(qty_req, pack):
                    warnings.append(f"«{r.get('product_name') or product_id_i}»: кількість {qty_req:g} не кратна тарі {pack:g}. Виправте.")
            else:
                new_qty = _round_to_pack(qty_req, pack, ROUND_TO_PACKAGE_MODE)
                if not _is_multiple(qty_req, pack):
                    warnings.append(
                        f"«{r.get('product_name') or product_id_i}» скориговано до кратної тарі: {qty_req:g} → {new_qty:g} (тара {pack:g})."
                    )
                qty_req = new_qty

        # формуємо чистий dict з гарантованими ключами
        rr = dict(r)
        rr["qty_requested"] = float(qty_req)
        rr["allow"] = float(allow)            # гарантовано є ключ
        rr["reserved"] = float(already_reserved)  # гарантовано є ключ
        rr["original_qty"] = float(original_qty)   # гарантовано є ключ

        # уніфікуємо ids теж як int або None (для consistency)
        rr["company_id"] = company_id_i
        rr["product_id"] = product_id_i
        rr["payer_id"] = payer_id_i
        rr["unit_id"] = _as_int(r.get("unit_id"))
        rr["manufacturer_id"] = _as_int(r.get("manufacturer_id"))
        rr["package_value"] = _as_float(r.get("package_value"), default=None)
        rr["qty_available"] = float(qty_av)

        adjusted.append(rr)

    # валідні і ненульові
    valid = []
    for r in adjusted:
        if _row_is_valid(r) and _as_float(r.get("qty_requested"), 0.0) > 0:
            valid.append(dict(r))  # ще раз гарантуємо звичайний dict

    if not valid:
        flash("Немає коректно заповнених позицій для створення заявки після перевірок (доступність, кратність).", "warning")
        return redirect(url_for("shipments_requests.index"))

    if warnings:
        for msg in warnings:
            flash(msg, "warning")

    payload = Markup(json.dumps(valid, ensure_ascii=False))
    # Можеш тимчасово передати перший рядок у шаблон для наочного дебагу:
    return render_template("shipments/preview_new.html", rows=valid, payload=payload, debug_row=(valid[0] if valid else None))



@shipments_requests_bp.route("/requests/shipments/submit_new", methods=["POST"])
def submit_new():
    """Створюємо заявку після підтвердження з preview_new (повторні перевірки доступності та кратності)."""
    try:
        rows = json.loads(request.form.get("payload") or "[]")
    except Exception:
        rows = []

    if not rows:
        flash("Немає даних для створення заявки.", "warning")
        return redirect(url_for("shipments_requests.index"))

    # Кеш name→id для фолбеків
    products_by_name       = {name: pid for name, pid in db.session.query(Product.name, Product.id).all()}
    units_by_name          = {name: uid for name, uid in db.session.query(Unit.name, Unit.id).all()}
    companies_by_name      = {name: cid for name, cid in db.session.query(Company.name, Company.id).all()}
    payers_by_name         = {name: pid for name, pid in db.session.query(Payer.name, Payer.id).all()}
    manufacturers_by_name  = {name: mid for name, mid in db.session.query(Manufacturer.name, Manufacturer.id).all()}

    # 1) створюємо заявку
    req = ShipmentRequest(number="PENDING", status="draft")
    db.session.add(req)
    db.session.flush()
    req.number = f"SR-{datetime.utcnow().year}-{req.id:04d}"
    db.session.flush()

    # Карта вже зарезервованих обсягів + локальне накопичення під час створення
        # --- NEW: name -> id backfill, щоб ключі резервів збігались ---
    products_by_name       = {name: pid for name, pid in db.session.query(Product.name, Product.id).all()}
    units_by_name          = {name: uid for name, uid in db.session.query(Unit.name, Unit.id).all()}
    companies_by_name      = {name: cid for name, cid in db.session.query(Company.name, Company.id).all()}
    payers_by_name         = {name: pid for name, pid in db.session.query(Payer.name, Payer.id).all()}
    manufacturers_by_name  = {name: mid for name, mid in db.session.query(Manufacturer.name, Manufacturer.id).all()}

    for r in rows:
        # якщо id порожній, але є назва — підставляємо id з довідника
        if _as_int(r.get("company_id")) is None and (r.get("company_name") or "").strip():
            cid = companies_by_name.get(r["company_name"])
            if cid: r["company_id"] = cid
        if _as_int(r.get("product_id")) is None and (r.get("product_name") or "").strip():
            pid = products_by_name.get(r["product_name"])
            if pid: r["product_id"] = pid
        if _as_int(r.get("payer_id")) is None and (r.get("payer_name") or "").strip():
            pay = payers_by_name.get(r["payer_name"])
            if pay: r["payer_id"] = pay
        if _as_int(r.get("unit_id")) is None and (r.get("unit_text") or "").strip():
            uid = units_by_name.get(r["unit_text"])
            if uid: r["unit_id"] = uid
        if _as_int(r.get("manufacturer_id")) is None and (r.get("manufacturer_name") or "").strip():
            mid = manufacturers_by_name.get(r["manufacturer_name"])
            if mid: r["manufacturer_id"] = mid
    # --- END NEW ---
    reserved_map = _build_reserved_map()
    errors = []

    # 2) додаємо позиції
    added = 0
    for r in rows:
        company_id_i = _as_int(r.get("company_id"))
        product_id_i = _as_int(r.get("product_id"))
        payer_id_i   = _as_int(r.get("payer_id"))
        unit_id_i    = _as_int(r.get("unit_id"))
        manuf_id_i   = _as_int(r.get("manufacturer_id"))
        pack_f       = _as_float(r.get("package_value"), default=None)
        qty_req      = _as_float(r.get("qty_requested"), default=0.0) or 0.0

        # фолбеки з назв
        if product_id_i is None and r.get("product_name"):
            product_id_i = products_by_name.get(r["product_name"])
        if unit_id_i is None and r.get("unit_text"):
            unit_id_i = units_by_name.get(r["unit_text"])
        if company_id_i is None and r.get("company_name"):
            company_id_i = companies_by_name.get(r["company_name"])
        if payer_id_i is None and r.get("payer_name"):
            payer_id_i = payers_by_name.get(r["payer_name"])
        if manuf_id_i is None and r.get("manufacturer_name"):
            manuf_id_i = manufacturers_by_name.get(r["manufacturer_name"])

        if product_id_i is None or unit_id_i is None or qty_req <= 0:
            continue

        # ---- контроль дублювання / перевищення дозволеного ----
        qty_av = _as_float(r.get("qty_available"), default=0.0) or 0.0
        key = _row_key(company_id_i, product_id_i, payer_id_i)
        already_reserved = reserved_map.get(key, 0.0)
        allow = max(0.0, qty_av - already_reserved)

        if qty_req > allow + 1e-9:
            errors.append(f"Запит «{r.get('product_name') or product_id_i}» по «{r.get('company_name') or company_id_i}»: "
                          f"запрошено {qty_req:g}, доступно {allow:g} з урахуванням поточних заявок.")
            continue

        # кратність тари (жорстко)
        if pack_f and not _is_multiple(qty_req, pack_f):
            if ROUND_TO_PACKAGE_MODE == "error":
                errors.append(f"Кількість {qty_req:g} не кратна тарі {pack_f:g} для «{r.get('product_name') or product_id_i}».")
                continue
            else:
                qty_req_corr = _round_to_pack(qty_req, pack_f, ROUND_TO_PACKAGE_MODE)
                # повторно перевіримо ліміт
                if qty_req_corr > allow + 1e-9:
                    errors.append(f"Після округлення до кратності (→ {qty_req_corr:g}) перевищено доступний ліміт {allow:g} "
                                  f"для «{r.get('product_name') or product_id_i}» по «{r.get('company_name') or company_id_i}».")
                    continue
                qty_req = qty_req_corr

        # оновлюємо локальний резерв, щоб наступні рядки врахували вже «зайняте» цією заявкою
        reserved_map[key] = reserved_map.get(key, 0.0) + qty_req

        item = ShipmentRequestItem(
            request_id=req.id,
            consumer_company_id=company_id_i,
            product_id=product_id_i,
            payer_id=payer_id_i,
            unit_id=unit_id_i,
            manufacturer_id=manuf_id_i,
            package_value=pack_f,
            qty_requested=qty_req,
            # снапшоти
            consumer_company_name=r.get("company_name"),
            product_name=r.get("product_name"),
            payer_name=r.get("payer_name"),
            unit_text=r.get("unit_text"),
            manufacturer_name=r.get("manufacturer_name"),
            package_text=r.get("package_text"),
        )
        db.session.add(item)
        added += 1

    # Якщо є помилки — не створюємо частково, відкочуємо
    if errors:
        db.session.rollback()
        for e in errors:
            flash(e, "warning")
        flash("Заявку не створено: виправте попередження і спробуйте ще раз.", "warning")
        return redirect(url_for("shipments_requests.index"))

    if added == 0:
        db.session.rollback()
        flash("Немає коректних позицій для створення заявки.", "warning")
        return redirect(url_for("shipments_requests.index"))

    req.status = "submitted"
    db.session.commit()
    flash("Заявку створено та подано на погодження складу.", "success")
    return redirect(url_for("warehouse_requests.view", request_id=req.id))


@shipments_requests_bp.route("/requests/shipments/<int:request_id>/preview")
def preview(request_id):
    """Класичний перегляд уже створеної заявки з БД."""
    req = ShipmentRequest.query.filter_by(id=request_id).first_or_404()
    return render_template("shipments/preview.html", req=req)


@shipments_requests_bp.route("/requests/shipments/<int:request_id>/submit", methods=["POST"])
def submit(request_id):
    """Якщо заявка вже є draft — подаємо її."""
    req = ShipmentRequest.query.filter_by(id=request_id).first_or_404()
    if req.status != "draft":
        flash("Цю заявку вже подано або скасовано.", "warning")
        return redirect(url_for("shipments_requests.preview", request_id=req.id))

    if not req.number or req.number == "PENDING":
        req.number = f"SR-{datetime.utcnow().year}-{req.id:04d}"

    req.status = "submitted"
    db.session.commit()
    flash("Заявку подано на погодження складу.", "success")
    return redirect(url_for("warehouse_requests.view", request_id=req.id))
