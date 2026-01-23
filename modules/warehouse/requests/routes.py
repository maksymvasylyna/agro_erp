from datetime import datetime
from flask import render_template, request, redirect, url_for, flash
from sqlalchemy import func, case
from extensions import db
from . import warehouse_requests_bp
from modules.requests.shipments.models import ShipmentRequest, ShipmentRequestItem
from modules.warehouse.models import StockTransaction

# Допоміжний розрахунок доступного залишку для конкретного item'а
def _available_for_item(it: ShipmentRequestItem) -> float:
    signed_qty = func.sum(
        case(
            (StockTransaction.tx_type == "IN",  StockTransaction.qty),
            (StockTransaction.tx_type == "OUT", -StockTransaction.qty),
            else_=0.0
        )
    )
    q = (
        db.session.query(signed_qty)
        .filter(StockTransaction.product_id == it.product_id)
        .filter(StockTransaction.unit_id == it.unit_id)
    )
    # фільтруємо за ключем балансу (дозволяємо NULL = NULL)
    if it.consumer_company_id is not None:
        q = q.filter(StockTransaction.consumer_company_id == it.consumer_company_id)
    else:
        q = q.filter(StockTransaction.consumer_company_id.is_(None))

    if it.payer_id is not None:
        q = q.filter(StockTransaction.payer_id == it.payer_id)
    else:
        q = q.filter(StockTransaction.payer_id.is_(None))

    if it.manufacturer_id is not None:
        q = q.filter(StockTransaction.manufacturer_id == it.manufacturer_id)
    else:
        q = q.filter(StockTransaction.manufacturer_id.is_(None))

    if it.package_value is not None:
        q = q.filter(StockTransaction.package_value == it.package_value)
    else:
        q = q.filter(StockTransaction.package_value.is_(None))

    val = q.scalar() or 0.0
    return float(val)

@warehouse_requests_bp.route("/warehouse/requests")
def list_submitted():
    to_approve = (
        ShipmentRequest.query
        .filter_by(status="submitted")
        .order_by(ShipmentRequest.created_at.asc())
        .all()
    )

    to_execute = (
        ShipmentRequest.query
        .filter_by(status="approved")
        .order_by(ShipmentRequest.created_at.asc())
        .all()
    )

    return render_template(
        "warehouse_requests/list.html",
        to_approve=to_approve,
        to_execute=to_execute,
    )
@warehouse_requests_bp.route("/warehouse/requests/<int:request_id>")
def view(request_id):
    req = ShipmentRequest.query.get_or_404(request_id)
    return render_template("warehouse_requests/view.html", req=req)

@warehouse_requests_bp.route("/warehouse/requests/<int:request_id>/approve", methods=["POST"])
def approve(request_id):
    req = ShipmentRequest.query.get_or_404(request_id)
    if req.status != "submitted":
        flash("Заявка вже опрацьована.", "warning")
        return redirect(url_for("warehouse_requests.view", request_id=req.id))
    req.status = "approved"
    db.session.commit()
    flash("Заявку погоджено.", "success")
    return redirect(url_for("warehouse_requests.execute", request_id=req.id))

@warehouse_requests_bp.route("/warehouse/requests/<int:request_id>/execute", methods=["GET", "POST"])
def execute(request_id):
    req = ShipmentRequest.query.get_or_404(request_id)
    if req.status not in ("approved", "submitted"):
        # дозволимо виконати одразу після submitted (якщо ще не натиснули approve)
        flash("Заявка має бути у статусі submitted або approved.", "warning")

    if request.method == "POST":
        any_done = False
        # проходимо по всіх items та шукаємо у формі поля qty_to_execute[item_id]
        for it in req.items:
            key = f"qty_to_execute[{it.id}]"
            val = request.form.get(key)
            if not val:
                continue
            try:
                qty = float(val)
            except ValueError:
                qty = 0.0

            remain = max(0.0, (it.qty_requested - it.qty_executed))
            if qty <= 0:
                continue
            if qty > remain:
                qty = remain  # м'яка корекція

            # додаткова перевірка доступного залишку на складі
            available_now = _available_for_item(it)
            if qty > available_now:
                qty = max(0.0, available_now)
            if qty <= 0:
                continue

            # ⚠️ тимчасово використовуємо warehouse_id=1 (за потреби підставиш актуальний)
            st = StockTransaction(
                product_id=it.product_id,
                unit_id=it.unit_id,
                qty=qty,
                tx_type="OUT",
                tx_date=datetime.utcnow(),
                note=f"Shipment request #{req.number}",
                source_kind="shipment_request",
                source_id=req.id,
                warehouse_id=1,  # TODO: обрати зі складу, якщо в тебе є модуль складів
                consumer_company_id=it.consumer_company_id,
                payer_id=it.payer_id,
                manufacturer_id=it.manufacturer_id,
                package_value=it.package_value,
            )
            db.session.add(st)

            it.qty_executed = (it.qty_executed or 0.0) + qty
            any_done = True

        if any_done:
            # якщо щось виконали — ставимо щонайменше approved (або executed, якщо все закрито)
            if req.status == "submitted":
                req.status = "approved"
            # якщо всі рядки виконані — закриваємо
            all_done = all((x.qty_executed >= x.qty_requested) for x in req.items)
            if all_done:
                req.status = "executed"
            db.session.commit()
            flash("Виконання збережено.", "success")
        else:
            flash("Немає позицій для виконання або кількість нульова.", "warning")

        return redirect(url_for("warehouse_requests.execute", request_id=req.id))

    # GET: показ форми виконання з підказками
    rows = []
    for it in req.items:
        remain = max(0.0, (it.qty_requested - it.qty_executed))
        avail = _available_for_item(it)
        rows.append({
            "item": it,
            "remain": remain,
            "available": avail,
        })
    return render_template("warehouse_requests/execute.html", req=req, rows=rows)
@warehouse_requests_bp.route("/warehouse/requests/<int:request_id>/delete", methods=["POST"])
def delete(request_id):
    req = ShipmentRequest.query.get_or_404(request_id)

    # збережемо дані ДО видалення (щоб не торкатись ORM після delete)
    req_number = req.number
    req_status = req.status

    # тимчасово для тесту: дозволимо видаляти лише submitted/approved
    if req_status not in ("submitted", "approved"):
        flash("Видалення дозволене лише для заявок у статусі submitted/approved.", "warning")
        return redirect(url_for("warehouse_requests.list_submitted"))

    # 1) спочатку видаляємо items
    ShipmentRequestItem.query.filter_by(request_id=req.id).delete(synchronize_session=False)

    # 2) потім саму заявку
    ShipmentRequest.query.filter_by(id=req.id).delete(synchronize_session=False)

    db.session.commit()

    flash(f"Заявку {req_number} видалено.", "success")
    return redirect(url_for("warehouse_requests.list_submitted"))


