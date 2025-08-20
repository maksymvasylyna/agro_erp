from flask import Blueprint, render_template, redirect, url_for, flash
from sqlalchemy.orm import joinedload
from extensions import db
from modules.purchases.payments.models import PaymentInbox

payments_bp = Blueprint(
    "payments",
    __name__,
    url_prefix="/purchases/payments",
    template_folder="templates",
)

@payments_bp.route("/", endpoint="index")
def index():
    """
    «Проплати — вхідні заявки»:
      - у шапці: підприємство (споживач), коротке резюме платників, к-сть рядків, статус, дата;
      - у деталях: Продукт, Тара, Кількість, Виробник, Платник.
    """
    q = (
        PaymentInbox.query
        .options(joinedload(PaymentInbox.company))
        .order_by(PaymentInbox.created_at.desc(), PaymentInbox.id.desc())
    )
    inboxes = q.limit(200).all()

    for r in inboxes:
        # Назва компанії (споживача)
        r.company_name = (r.company.name if getattr(r, "company", None) else None)

        # --- НОРМАЛІЗАЦІЯ items_json ---
        raw = getattr(r, "items_json", None)

        # допуски на старі/криві формати
        if isinstance(raw, dict):
            rows = [raw]  # одиничний словник -> список з одного елемента
        elif isinstance(raw, list):
            rows = raw
        else:
            # будь-що інше (int/str/None/float) -> порожній список
            rows = []

        norm_rows = []
        payer_order = []
        seen_payers = set()

        for it in rows:
            if not isinstance(it, dict):
                # пропускаємо все, що не словник
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

            if payer_name and payer_name != "—" and payer_name not in seen_payers:
                seen_payers.add(payer_name)
                payer_order.append(payer_name)

            norm_rows.append({
                "product_name": product_name,
                "package": package,
                "qty": qty,
                "manufacturer_name": manufacturer_name,
                "payer_name": payer_name,
            })

        # стабільне сортування
        norm_rows.sort(key=lambda x: ((x.get("product_name") or "").lower(),
                                      (x.get("payer_name") or "").lower()))
        r.items = norm_rows
        r.payers_summary = ", ".join(payer_order) if payer_order else "—"
        r.rows_count = len(norm_rows)

    return render_template(
        "payments/index.html",
        items=inboxes,
        title="Проплати — вхідні заявки",
        header="💳 Проплати — вхідні заявки",
    )


# ------- Видалення однієї заявки -------
@payments_bp.post("/<int:inbox_id>/delete", endpoint="delete")
def delete(inbox_id: int):
    inbox = PaymentInbox.query.get_or_404(inbox_id)
    db.session.delete(inbox)
    db.session.commit()
    flash(f"Заявку #{inbox_id} видалено.", "success")
    return redirect(url_for("payments.index"))

# ------- Повне очищення таблиці -------
@payments_bp.post("/clear", endpoint="clear")
def clear_all():
    deleted = PaymentInbox.query.delete(synchronize_session=False)
    db.session.commit()
    flash(f"Очистка виконана. Видалено заявок: {deleted}.", "success")
    return redirect(url_for("payments.index"))
