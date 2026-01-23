from flask import render_template, request, redirect, url_for, flash
from sqlalchemy import func, case, and_
from sqlalchemy.orm import joinedload
from extensions import db
from . import warehouse_bp
from .models import StockTransaction

# Моделі
from modules.purchases.payments.models import PaymentInbox
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from modules.reference.payers.models import Payer
from modules.reference.manufacturers.models import Manufacturer



# ---------- ХЕЛПЕРИ ----------

def _is_paid(inbox: PaymentInbox) -> bool:
    if hasattr(inbox, "status") and (inbox.status or "").lower() == "оплачено":
        return True
    if hasattr(inbox, "is_paid") and bool(inbox.is_paid):
        return True
    return False


def _normalize_items_list(items_json):
    # ... без змін ...
    if isinstance(items_json, dict):
        rows = [items_json]
    elif isinstance(items_json, list):
        rows = items_json
    else:
        rows = []

    out = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        product_id        = it.get("product_id")
        product_name      = it.get("product_name") or (f"#{product_id}" if product_id else "—")
        package           = it.get("package") or "—"
        manufacturer_name = it.get("manufacturer_name") or "—"
        payer_name        = it.get("payer_name") or "—"

        qty = it.get("qty")
        try:
            qty = float(qty) if qty is not None else None
        except Exception:
            qty = None

        if product_id and qty and qty > 0:
            out.append({
                "product_id": int(product_id),
                "product_name": product_name,
                "package": package,
                "manufacturer_name": manufacturer_name,
                "payer_name": payer_name,
                "qty": float(qty),
            })
    return out


def _group_ordered_by_product(rows):
    # ... без змін ...
    agg = {}
    for r in rows:
        pid = r["product_id"]
        agg[pid] = agg.get(pid, 0.0) + r["qty"]
    return agg


def _received_by_product(inbox_id: int, product_ids: list[int]) -> dict[int, float]:
    # ... без змін ...
    if not product_ids:
        return {}
    pairs = (
        db.session.query(
            StockTransaction.product_id,
            func.coalesce(func.sum(StockTransaction.qty), 0.0)
        )
        .filter(
            StockTransaction.source_kind == "payment_inbox",
            StockTransaction.source_id == inbox_id,
            StockTransaction.tx_type == "IN",
            StockTransaction.product_id.in_(product_ids)
        )
        .group_by(StockTransaction.product_id)
        .all()
    )
    return {pid: float(total) for pid, total in pairs}


def _received_by_line(inbox_id: int) -> dict[int, float]:
    # ... без змін ...
    pairs = (
        db.session.query(
            StockTransaction.source_line_idx,
            func.coalesce(func.sum(StockTransaction.qty), 0.0)
        )
        .filter(
            StockTransaction.source_kind == "payment_inbox",
            StockTransaction.source_id == inbox_id,
            StockTransaction.tx_type == "IN",
        )
        .group_by(StockTransaction.source_line_idx)
        .all()
    )
    return {int(idx): float(total or 0.0) for idx, total in pairs}


def _unit_text(u: Unit) -> str:
    # ... без змін ...
    return (
        getattr(u, "short_name", None)
        or getattr(u, "symbol", None)
        or getattr(u, "name", None)
        or ""
    )


# ---------- РОУТИ КАРКАСУ ----------

@warehouse_bp.route("/")
def index():
    return render_template("warehouse/index.html")


@warehouse_bp.route("/stock", endpoint="stock_index")
def stock_index():
    """
    Залишки складу з фільтрами:
    - product_id: за продуктом (ID)
    - consumer: за споживачем (текст останнього IN по продукту)
    Показуються позиції з додатним балансом (> 0).
    """
    wid = request.args.get("warehouse_id", type=int) or 1
    product_id = request.args.get("product_id", type=int)
    consumer = (request.args.get("consumer") or "").strip() or None

    # баланс: IN = +qty, OUT = -qty
    balance_expr = func.coalesce(
        func.sum(
            case(
                (StockTransaction.tx_type == "IN", StockTransaction.qty),
                else_=-StockTransaction.qty,
            )
        ),
        0.0,
    ).label("balance")

    # підзапит: останній IN по кожному продукту (знімок для відображення/фільтра)
    last_in = (
        db.session.query(
            StockTransaction.product_id.label("product_id"),
            StockTransaction.tx_date.label("tx_date"),
            StockTransaction.product_name.label("product_name"),
            StockTransaction.unit_text.label("unit_text"),
            StockTransaction.consumer_company_name.label("consumer_company_name"),
            StockTransaction.payer_name.label("payer_name"),
            StockTransaction.package_text.label("package_text"),
            StockTransaction.manufacturer_name.label("manufacturer_name"),
            func.row_number().over(
                partition_by=StockTransaction.product_id,
                order_by=[StockTransaction.tx_date.desc(), StockTransaction.id.desc()],
            ).label("rn"),
        )
        .filter(
            StockTransaction.warehouse_id == wid,
            StockTransaction.tx_type == "IN",
        )
        .subquery("last_in")
    )

    # основний запит: агрегація балансу + join знімка останнього IN
    query = (
        db.session.query(
            Product,
            Unit,
            balance_expr,
            last_in.c.tx_date,
            last_in.c.consumer_company_name,
            last_in.c.payer_name,
            last_in.c.package_text,
            last_in.c.manufacturer_name,
            last_in.c.product_name.label("product_name_snapshot"),
            last_in.c.unit_text.label("unit_text_snapshot"),
        )
        .join(StockTransaction, StockTransaction.product_id == Product.id)
        .join(Unit, Unit.id == Product.unit_id)
        .outerjoin(last_in, and_(last_in.c.product_id == Product.id, last_in.c.rn == 1))
        .filter(StockTransaction.warehouse_id == wid)
    )

    # застосувати фільтри
    if product_id:
        query = query.filter(Product.id == product_id)
    if consumer:
        query = query.filter(last_in.c.consumer_company_name == consumer)

    query = (
        query.group_by(
            Product.id,
            Unit.id,
            last_in.c.tx_date,
            last_in.c.consumer_company_name,
            last_in.c.payer_name,
            last_in.c.package_text,
            last_in.c.manufacturer_name,
            last_in.c.product_name,
            last_in.c.unit_text,
        )
        .having(balance_expr > 1e-12)  # тільки додатні залишки
        .order_by(Product.name.asc())
    )

    # селект-опції
    product_opts = (
        db.session.query(Product.id, Product.name)
        .join(StockTransaction, StockTransaction.product_id == Product.id)
        .filter(StockTransaction.warehouse_id == wid)
        .group_by(Product.id, Product.name)   # 🔧 важливо для Postgres
        .order_by(Product.name.asc())
        .all()
    )
    consumer_opts = (
        db.session.query(StockTransaction.consumer_company_name)
        .filter(
            StockTransaction.warehouse_id == wid,
            StockTransaction.tx_type == "IN",
            StockTransaction.consumer_company_name.isnot(None),
            StockTransaction.consumer_company_name != "",
        )
        .distinct()
        .order_by(StockTransaction.consumer_company_name.asc())
        .all()
    )
    consumer_opts = [c[0] for c in consumer_opts]

    # сформувати ряди для шаблону
    rows = []
    for (
        p,
        u,
        balance,
        last_dt,
        consumer_name,
        payer,
        package,
        manufacturer,
        prod_name_snap,
        unit_text_snap,
    ) in query.all():
        rows.append(
            {
                "product": p,
                "unit_text": (
                    getattr(u, "short_name", None)
                    or getattr(u, "symbol", None)
                    or getattr(u, "name", None)
                    or ""
                ),
                "balance": float(balance or 0.0),
                # знімок останнього IN (для відображення/фільтра)
                "last_in_date": last_dt,
                "last_consumer": consumer_name,
                "last_payer": payer,
                "last_package": package,
                "last_manufacturer": manufacturer,
                "last_product_name": (prod_name_snap or p.name),
                "last_unit_text": (
                    unit_text_snap
                    or getattr(u, "short_name", None)
                    or getattr(u, "symbol", None)
                    or getattr(u, "name", None)
                    or ""
                ),
            }
        )

    return render_template(
        "warehouse/stock_index.html",
        rows=rows,
        product_opts=product_opts,
        consumer_opts=consumer_opts,
        product_id=product_id,
        consumer=consumer,
        warehouse_id=wid,
    )


@warehouse_bp.route("/in")
def stock_in_placeholder():
    return render_template("warehouse/stock_in_placeholder.html")


@warehouse_bp.route("/out")
def stock_out_placeholder():
    return render_template("warehouse/stock_out_placeholder.html")


# ---------- ЖУРНАЛ НАДХОДЖЕНЬ (очікують + історія) ----------

@warehouse_bp.route("/in-journal")
def in_journal():
    # ... без змін повністю ...
    inboxes = (
        PaymentInbox.query.options(joinedload(PaymentInbox.company))
        .order_by(PaymentInbox.created_at.desc(), PaymentInbox.id.desc())
        .limit(200)
        .all()
    )

    pending = []
    for inbox in inboxes:
        if not _is_paid(inbox):
            continue

        items = _normalize_items_list(getattr(inbox, "items_json", None))
        if not items:
            continue

        ordered_map = _group_ordered_by_product(items)
        product_ids = list(ordered_map.keys())

        prod_rows = (
            db.session.query(Product, Unit)
            .join(Unit, Unit.id == Product.unit_id)
            .filter(Product.id.in_(product_ids))
            .all()
        )
        prod_map = {p.id: (p, u) for p, u in prod_rows}

        received_map = _received_by_product(inbox.id, product_ids)

        total_ordered = total_received = 0.0
        any_received_gt0 = False
        any_remaining_gt0 = False

        for pid, ordered in ordered_map.items():
            rec = received_map.get(pid, 0.0)
            remaining = max(0.0, ordered - rec)

            total_ordered += ordered
            total_received += rec
            if rec > 0:
                any_received_gt0 = True
            if remaining > 0:
                any_remaining_gt0 = True

        if not any_remaining_gt0:
            continue

        fulfillment = "Частково виконано" if any_received_gt0 else "Не виконано"

        seen, payers_order = set(), []
        for it in items:
            pn = it.get("payer_name")
            if pn and pn != "—" and pn not in seen:
                seen.add(pn)
                payers_order.append(pn)

        pending.append({
            "inbox": inbox,
            "company_name": inbox.company.name if getattr(inbox, "company", None) else None,
            "payers_summary": ", ".join(payers_order) if payers_order else "—",
            "rows_count": len(items),
            "total_ordered": total_ordered,
            "total_received": total_received,
            "fulfillment": fulfillment,
            "items": items,
        })

    history_raw = (
        db.session.query(StockTransaction, Product, Unit)
        .join(Product, Product.id == StockTransaction.product_id)
        .join(Unit, Unit.id == StockTransaction.unit_id)
        .filter(StockTransaction.tx_type == "IN")
        .order_by(StockTransaction.tx_date.desc(), StockTransaction.id.desc())
        .limit(500)
        .all()
    )
    history = []
    for st, p, u in history_raw:
        history.append({
            "tx_date": st.tx_date,
            "product_name": p.name,
            "qty": st.qty,
            "unit_text": _unit_text(u),
            "source_kind": st.source_kind,
            "source_id": st.source_id,
        })

    return render_template("warehouse/in_journal.html", pending=pending, history=history)


# ---------- ПРИЙМАННЯ (ОПРИБУТКУВАННЯ) ПО КОЖНІЙ ПОЗИЦІЇ ----------

@warehouse_bp.route("/receive/<int:inbox_id>", methods=["GET", "POST"])
def receive(inbox_id: int):
    inbox = PaymentInbox.query.get_or_404(inbox_id)
    if not _is_paid(inbox):
        flash("Приймання дозволено лише після статусу «Оплачено».", "warning")
        return redirect(url_for("warehouse.in_journal"))

    items = _normalize_items_list(getattr(inbox, "items_json", None))
    if not items:
        flash("У заявці немає валідних позицій.", "warning")
        return redirect(url_for("warehouse.in_journal"))

    # --- МАПІНГ ДОВІДНИКІВ ДЛЯ СТРОГОГО СКЛАДСЬКОГО КЛЮЧА (ID) ---
    payer_names = {
        it.get("payer_name")
        for it in items
        if it.get("payer_name") and it.get("payer_name") != "—"
    }
    manufacturer_names = {
        it.get("manufacturer_name")
        for it in items
        if it.get("manufacturer_name") and it.get("manufacturer_name") != "—"
    }

    payer_map = {}
    if payer_names:
        payer_rows = (
            db.session.query(Payer)
            .filter(Payer.name.in_(list(payer_names)))
            .all()
        )
        payer_map = {p.name: p.id for p in payer_rows}

    manufacturer_map = {}
    if manufacturer_names:
        man_rows = (
            db.session.query(Manufacturer)
            .filter(Manufacturer.name.in_(list(manufacturer_names)))
            .all()
        )
        manufacturer_map = {m.name: m.id for m in man_rows}

    consumer_company_id = getattr(inbox, "company_id", None)

    # --- Завантаження продуктів/одиниць ---
    pids = list({it["product_id"] for it in items})
    prod_rows = (
        db.session.query(Product, Unit)
        .join(Unit, Unit.id == Product.unit_id)
        .filter(Product.id.in_(pids))
        .all()
    )
    prod_map = {p.id: (p, u) for p, u in prod_rows}

    received_per_line = _received_by_line(inbox_id)

    rows = []
    for idx, it in enumerate(items, start=1):
        p, u = prod_map.get(it["product_id"], (None, None))
        if p is None or u is None:
            continue

        ordered = it["qty"]
        received = received_per_line.get(idx, 0.0)
        remaining = max(0.0, ordered - received)

        unit_text = _unit_text(u)
        rows.append({
            "idx": idx,
            "product": p,
            "unit_text": unit_text,
            "product_name_src": it.get("product_name") or p.name,
            "package": it.get("package") or "—",
            "manufacturer_name": it.get("manufacturer_name") or "—",
            "payer_name": it.get("payer_name") or "—",
            "ordered": ordered,
            "received": received,
            "remaining": remaining,
        })

    if all(r["remaining"] <= 1e-12 for r in rows):
        flash("Усі позиції цієї заявки вже оприбутковані.", "info")
        return redirect(url_for("warehouse.in_journal"))

    if request.method == "POST":
        created = 0
        consumer_name = getattr(getattr(inbox, "company", None), "name", None) or "—"

        for r in rows:
            field = f"receive_now_{r['idx']}"
            raw_val = (request.form.get(field) or "").strip()
            if raw_val == "":
                continue

            try:
                receive_now = float(raw_val.replace(",", "."))
            except ValueError:
                flash(f"Невірне число для позиції #{r['idx']}.", "danger")
                return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

            if receive_now < 0:
                flash(f"Кількість не може бути від’ємною (позиція #{r['idx']}).", "danger")
                return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

            if receive_now - r["remaining"] > 1e-9:
                flash(f"Перевищення заборонене: {r['product'].name} — максимум {r['remaining']:.3f}.", "danger")
                return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

            if receive_now > 0:
                payer_name = r["payer_name"]
                manufacturer_name = r["manufacturer_name"]

                payer_id = payer_map.get(payer_name) if payer_name and payer_name != "—" else None
                manufacturer_id = manufacturer_map.get(manufacturer_name) if manufacturer_name and manufacturer_name != "—" else None

                # 🔴 Жорстка перевірка — щоб не було "NULL-кошика" і плутанини в бухгалтерії
                if payer_name and payer_name != "—" and payer_id is None:
                    flash(f"Платник «{payer_name}» не знайдений у довіднику.", "danger")
                    return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

                if manufacturer_name and manufacturer_name != "—" and manufacturer_id is None:
                    flash(f"Виробник «{manufacturer_name}» не знайдений у довіднику.", "danger")
                    return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

                st = StockTransaction(
                    product_id=r["product"].id,
                    unit_id=r["product"].unit_id,
                    qty=receive_now,
                    tx_type="IN",
                    warehouse_id=1,

                    source_kind="payment_inbox",
                    source_id=inbox_id,
                    source_line_idx=r["idx"],

                    # ✅ КЛЮЧІ ДЛЯ СТРОГОГО ЗБІГУ (ID)
                    consumer_company_id=consumer_company_id,
                    payer_id=payer_id,
                    manufacturer_id=manufacturer_id,
                    package_value=None,  # поки що (бо в items_json у тебе package як текст)

                    # 📝 Тексти для UI/аудиту
                    product_name=r["product_name_src"],
                    unit_text=r["unit_text"],
                    consumer_company_name=consumer_name,
                    payer_name=payer_name,
                    package_text=r["package"],
                    manufacturer_name=manufacturer_name,

                    note=f"PaymentInbox #{inbox_id}, line #{r['idx']}",
                )
                db.session.add(st)
                created += 1

        if created == 0:
            flash("Немає рядків для оприбуткування.", "warning")
            return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)

        db.session.commit()
        flash(f"Оприбуткувань створено: {created}.", "success")
        return redirect(url_for("warehouse.in_journal"))

    return render_template("warehouse/receive_form.html", inbox=inbox, rows=rows)



@warehouse_bp.post("/stock/clear", endpoint="stock_clear")
def stock_clear():
    """Очистити всі транзакції (IN/OUT) центрального складу та скинути залишок у нуль."""
    wid = request.form.get("warehouse_id", type=int) or 1
    deleted = (
        db.session.query(StockTransaction)
        .filter(StockTransaction.warehouse_id == wid)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    flash(f"Очищено транзакцій складу #{wid}: {deleted}.", "success")
    return redirect(url_for("warehouse.stock_index"))
