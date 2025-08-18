# modules/purchases/payer_allocation/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from extensions import db
from .models import PayerAllocation
from .forms import AllocationFilterForm, BulkAssignForm
from modules.reference.payers.models import Payer
from .services import sync_from_plans  # 👈 додано

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

    # 🔄 Первинний автосинк: якщо пусто — підтягуємо з планів один раз
    if not rows:
        stats = sync_from_plans()
        # Якщо щось підтягнули — покажемо повідомлення та перезавантажимо сторінку
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
