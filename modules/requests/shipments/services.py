# modules/requests/shipments/services.py
from sqlalchemy import func, case, or_
from extensions import db
from modules.warehouse.models import StockTransaction
from modules.reference.products.models import Product
from modules.reference.companies.models import Company
from modules.reference.payers.models import Payer
from modules.reference.units.models import Unit
from modules.reference.manufacturers.models import Manufacturer
from datetime import datetime

def generate_request_number(prefix: str = "SR") -> str:
    year = datetime.utcnow().year
    total = db.session.query(func.count(StockTransaction.id)).scalar() or 0
    return f"{prefix}-{year}-{total + 1:04d}"

def get_stock_balances(company_id: int | None = None,
                       product_id: int | None = None) -> list[dict]:
    signed_qty = func.sum(
        case(
            (StockTransaction.tx_type == "IN",  StockTransaction.qty),
            (StockTransaction.tx_type == "OUT", -StockTransaction.qty),
            else_=0.0
        )
    ).label("qty_available")

    # снапшоти для fallback'ів (беремо MAX як представника в групі)
    company_snap = func.max(StockTransaction.consumer_company_name).label("company_snap")
    payer_snap   = func.max(StockTransaction.payer_name).label("payer_snap")
    unit_snap    = func.max(StockTransaction.unit_text).label("unit_snap")
    manuf_snap   = func.max(StockTransaction.manufacturer_name).label("manuf_snap")
    pack_snap    = func.max(StockTransaction.package_text).label("pack_snap")

    q = (
        db.session.query(
            StockTransaction.consumer_company_id.label("company_id"),
            StockTransaction.product_id.label("product_id"),
            StockTransaction.payer_id.label("payer_id"),
            StockTransaction.unit_id.label("unit_id"),
            StockTransaction.manufacturer_id.label("manufacturer_id"),
            StockTransaction.package_value.label("package_value"),
            company_snap, payer_snap, unit_snap, manuf_snap, pack_snap,
            signed_qty
        )
        .group_by(
            StockTransaction.consumer_company_id,
            StockTransaction.product_id,
            StockTransaction.payer_id,
            StockTransaction.unit_id,
            StockTransaction.manufacturer_id,
            StockTransaction.package_value,
        )
        .having(signed_qty > 0)
    )

    # незалежні фільтри з fallback
    if product_id:
        q = q.filter(StockTransaction.product_id == product_id)

    if company_id:
        comp = db.session.get(Company, company_id)
        comp_name = comp.name if comp else None
        if comp_name:
            q = q.filter(
                or_(
                    StockTransaction.consumer_company_id == company_id,
                    # fallback на старі записи без ID, але з назвою
                    StockTransaction.consumer_company_id.is_(None),
                    # і ця назва збігається
                )
            ).filter(StockTransaction.consumer_company_name == comp_name)

    rows = q.all()
    if not rows:
        return []

    # дозбагачення назвами (для тих, де є *_id)
    company_ids = [r.company_id for r in rows if r.company_id]
    product_ids = [r.product_id for r in rows if r.product_id]
    payer_ids   = [r.payer_id for r in rows if r.payer_id]
    unit_ids    = [r.unit_id for r in rows if r.unit_id]
    manuf_ids   = [r.manufacturer_id for r in rows if r.manufacturer_id]

    companies = {c.id: c for c in db.session.query(Company).filter(Company.id.in_(set(company_ids))).all()} if company_ids else {}
    products  = {p.id: p for p in db.session.query(Product).filter(Product.id.in_(set(product_ids))).all()} if product_ids else {}
    payers    = {p.id: p for p in db.session.query(Payer).filter(Payer.id.in_(set(payer_ids))).all()} if payer_ids else {}
    units     = {u.id: u for u in db.session.query(Unit).filter(Unit.id.in_(set(unit_ids))).all()} if unit_ids else {}
    manufs    = {m.id: m for m in db.session.query(Manufacturer).filter(Manufacturer.id.in_(set(manuf_ids))).all()} if manuf_ids else {}

    result = []
    for r in rows:
        company_name = companies.get(r.company_id).name if r.company_id in companies else (r.company_snap or None)
        product_name = products.get(r.product_id).name if r.product_id in products else None
        payer_name   = payers.get(r.payer_id).name if r.payer_id in payers else (r.payer_snap or None)
        unit_name    = units.get(r.unit_id).name if r.unit_id in units else (r.unit_snap or None)
        manuf_name   = manufs.get(r.manufacturer_id).name if r.manufacturer_id in manufs else (r.manuf_snap or None)

        result.append({
            "company_id": r.company_id,
            "company_name": company_name,
            "product_id": r.product_id,
            "product_name": product_name,
            "payer_id": r.payer_id,
            "payer_name": payer_name,
            "unit_id": r.unit_id,
            "unit_name": unit_name,
            "manufacturer_id": r.manufacturer_id,
            "manufacturer_name": manuf_name,
            "package_value": r.package_value,
            "package_text": r.pack_snap,
            "qty_available": float(r.qty_available),
        })
    return result
