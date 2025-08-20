# modules/purchases/payer_allocation/services.py
# -*- coding: utf-8 -*-
"""
Сервіси для підблоку 'Розподіл між платниками', без жорстких імпортів ORM-моделей Field/Product.
Працює напряму з таблицями через db.metadata.tables['fields'] та ['products'].
Підтримує Approved* або звичайні Plan/Treatment, консолідацію та зворотну сумісність.
"""

from __future__ import annotations
import json

import importlib
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_, func
from extensions import db
from .models import PayerAllocation


# ----------------------------- утиліти планів/таблиць -----------------------------

def _load_plan_models():
    """Повертає (Plan, Treatment, use_approved: bool)."""
    # Approved*
    try:
        mod = importlib.import_module("modules.plans.approved_plans.models")
        Plan = getattr(mod, "ApprovedPlan")
        Treatment = getattr(mod, "ApprovedTreatment")
        return Plan, Treatment, True
    except Exception:
        pass
    # Звичайні
    mod = importlib.import_module("modules.plans.models")
    Plan = getattr(mod, "Plan")
    Treatment = getattr(mod, "Treatment")
    return Plan, Treatment, False


def _get_table(name: str):
    """Дістає Table з загальної metadata за ім'ям (наприклад, 'fields', 'products')."""
    tbl = db.metadata.tables.get(name)
    if tbl is None:
        raise RuntimeError(f"Не знайдена таблиця '{name}' у db.metadata.tables")
    return tbl


def _table_has_col(table, col: str) -> bool:
    return col in table.c


def _detect_col(table, names: List[str]):
    """Повертає table.c.<col> першої наявної назви з 'names' або None."""
    for n in names:
        if _table_has_col(table, n):
            return getattr(table.c, n)
    return None


# ----------------------------- структури даних -----------------------------

@dataclass(frozen=True)
class AggKey:
    field_id: int
    product_id: int


@dataclass
class AggValue:
    company_id: int
    qty: float


@dataclass
class SyncStats:
    added: int = 0
    updated: int = 0
    marked_stale: int = 0
    total_active: int = 0

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "marked_stale": self.marked_stale,
            "total_active": self.total_active,
        }


# ----------------------------- побудова запиту до планів (через таблиці) -----------------------------

def _build_plans_query(
    *,
    only_approved_in_plain: bool = True,
    company_id: Optional[int] = None,
    field_ids: Optional[Sequence[int]] = None,
    product_ids: Optional[Sequence[int]] = None,
):
    """
    Формує запит до (Approved)Plan/Treatment та таблиці fields:
      повертає: field_id, company_id, product_id, qty = fields.area * treatments.rate.
    БЕЗ імпорту ORM-класів Field/Product.
    """
    Plan, Treatment, use_approved = _load_plan_models()
    fields_t = _get_table("fields")
    plans_t = Plan.__table__
    treats_t = Treatment.__table__

    q = (
        db.session.query(
            fields_t.c.id.label("field_id"),
            fields_t.c.company_id.label("company_id"),
            treats_t.c.product_id.label("product_id"),
            (fields_t.c.area * treats_t.c.rate).label("qty"),
        )
        .select_from(
            fields_t
            .join(plans_t, plans_t.c.field_id == fields_t.c.id)
            .join(treats_t, treats_t.c.plan_id == plans_t.c.id)
        )
    )

    conds = []
    if company_id:
        conds.append(fields_t.c.company_id == company_id)
    if field_ids:
        conds.append(fields_t.c.id.in_(list(field_ids)))
    if product_ids:
        conds.append(treats_t.c.product_id.in_(list(product_ids)))
    if conds:
        q = q.filter(and_(*conds))

    # Для звичайних планів — по можливості лишаємо approved/готові
    if not use_approved and only_approved_in_plain:
        variants = []
        if _table_has_col(plans_t, "is_approved"):
            variants.append(plans_t.c.is_approved == True)  # noqa: E712
        if _table_has_col(plans_t, "status"):
            variants.append(plans_t.c.status.in_(["затверджений", "approved", "готовий", "ready"]))
        if variants:
            q = q.filter(or_(*variants))

    return q


# ----------------------------- агрегація -----------------------------

def _aggregate_rows(plan_rows: Iterable) -> Tuple[Dict[AggKey, AggValue], List[int]]:
    agg: Dict[AggKey, AggValue] = {}
    product_ids: set = set()

    for r in plan_rows:
        f_id = int(r.field_id)
        p_id = int(r.product_id)
        qty = float(r.qty or 0.0)
        c_id = int(r.company_id)

        key = AggKey(field_id=f_id, product_id=p_id)
        if key in agg:
            agg[key].qty += qty
        else:
            agg[key] = AggValue(company_id=c_id, qty=qty)
        product_ids.add(p_id)

    return agg, list(product_ids)


# ----------------------------- products meta для синку -----------------------------

def _load_products_meta(product_ids: Sequence[int]) -> Dict[int, dict]:
    """
    Пакетно тягне з таблиці 'products' метадані для синку:
      - manufacturer_id (manufacturer_id/producer_id/vendor_id/maker_id/brand_id)
      - unit_id (unit_id/uom_id)
    """
    if not product_ids:
        return {}

    products_t = _get_table("products")
    manuf_id_c = _detect_col(products_t, ["manufacturer_id", "producer_id", "vendor_id", "maker_id", "brand_id"])
    unit_id_c  = _detect_col(products_t, ["unit_id", "uom_id"])

    cols = [products_t.c.id]
    if manuf_id_c is not None:
        cols.append(manuf_id_c.label("manufacturer_id"))
    if unit_id_c is not None:
        cols.append(unit_id_c.label("unit_id"))

    rows = db.session.query(*cols).filter(products_t.c.id.in_(list(product_ids))).all()

    out: Dict[int, dict] = {}
    for r in rows:
        d = {"manufacturer_id": None, "unit_id": None}
        if hasattr(r, "manufacturer_id"):
            d["manufacturer_id"] = int(r.manufacturer_id) if r.manufacturer_id is not None else None
        if hasattr(r, "unit_id"):
            d["unit_id"] = int(r.unit_id) if r.unit_id is not None else None
        out[int(r.id)] = d

    return out


# ----------------------------- допоміжні хелпери назв/тари -----------------------------

def _name_col(table):
    """Колонка з назвою: name/title/full_name/caption, якщо є."""
    return _detect_col(table, ["name", "title", "full_name", "caption"])


def _fetch_names(table_name: str, ids: set) -> dict:
    """Повертає {id: name} з довільної таблиці; безпечно повертає {} якщо таблиці/колонки нема."""
    if not ids:
        return {}
    try:
        t = _get_table(table_name)
    except Exception:
        return {}
    name_c = _name_col(t)
    if name_c is None:
        return {}
    rows = db.session.query(t.c.id, name_c.label("name")).filter(t.c.id.in_(list(ids))).all()
    return {int(r.id): r.name for r in rows}


def _fetch_product_package(prod_ids: set) -> dict:
    """
    {product_id: package_text}. Підтримує:
      - текстові колонки: container/package/packaging/package_name/pack/pack_name/package_size/pack_size/tara
      - FK: container_id/package_id/pack_id/tara_id/packing_id із підтягуванням назв
    """
    if not prod_ids:
        return {}
    try:
        products_t = _get_table("products")
    except Exception:
        return {}

    # 1) текст
    txt_c = _detect_col(
        products_t,
        ["container", "package", "packaging", "package_name", "pack", "pack_name", "package_size", "pack_size", "tara"],
    )
    if txt_c is not None:
        rows = db.session.query(products_t.c.id, txt_c.label("pkg")).filter(products_t.c.id.in_(list(prod_ids))).all()
        return {int(r.id): (str(r.pkg) if r.pkg is not None else None) for r in rows}

    # 2) FK
    fk_c = _detect_col(products_t, ["container_id", "package_id", "pack_id", "tara_id", "packing_id"])
    if fk_c is None:
        return {}

    rows = db.session.query(products_t.c.id, fk_c.label("pkg_id")).filter(products_t.c.id.in_(list(prod_ids))).all()
    ids = {int(r.pkg_id) for r in rows if r.pkg_id is not None}
    if not ids:
        return {}

    for tbl in ["containers", "packages", "packs", "taras", "packagings"]:
        try:
            t = _get_table(tbl)
            name_c = _name_col(t)
            if name_c is None:
                continue
            name_rows = db.session.query(t.c.id, name_c.label("name")).filter(t.c.id.in_(list(ids))).all()
            namemap = {int(n.id): n.name for n in name_rows}
            return {int(r.id): namemap.get(int(r.pkg_id)) for r in rows}
        except Exception:
            continue

    return {}


def _fetch_product_manufacturer_name(prod_ids: set) -> dict:
    """
    {product_id: manufacturer_name} з текстових колонок products (fallback),
    якщо немає або не використовується FK на таблицю виробників.
    """
    if not prod_ids:
        return {}
    try:
        products_t = _get_table("products")
    except Exception:
        return {}

    txt_c = _detect_col(products_t, ["manufacturer_name", "producer", "producer_name", "brand", "maker", "vendor"])
    if txt_c is None:
        return {}

    rows = db.session.query(products_t.c.id, txt_c.label("mname")).filter(products_t.c.id.in_(list(prod_ids))).all()
    return {int(r.id): (str(r.mname) if r.mname is not None else None) for r in rows}


# ----------------------------- upsert + stale -----------------------------

def _get_existing_map() -> Dict[AggKey, PayerAllocation]:
    existing = {}
    for row in PayerAllocation.query.all():
        existing[AggKey(row.field_id, row.product_id)] = row
    return existing


def _upsert_allocations(
    agg_map: Dict[AggKey, AggValue],
    products_meta: Dict[int, dict],
    now: datetime,
) -> Tuple[int, int, set]:
    existing = _get_existing_map()

    added = 0
    updated = 0
    active_keys = set()

    for key, val in agg_map.items():
        active_keys.add(key)
        meta = products_meta.get(key.product_id, {})
        manufacturer_id = meta.get("manufacturer_id")
        unit_id = meta.get("unit_id")

        if key in existing:
            row = existing[key]
            row.company_id = val.company_id
            row.qty = val.qty
            row.manufacturer_id = manufacturer_id
            row.unit_id = unit_id
            row.status = "active"
            row.updated_at = now
            updated += 1
        else:
            db.session.add(PayerAllocation(
                field_id=key.field_id,
                company_id=val.company_id,
                product_id=key.product_id,
                manufacturer_id=manufacturer_id,
                unit_id=unit_id,
                qty=val.qty,
                status="active",
                created_at=now,
                updated_at=now,
            ))
            added += 1

    return added, updated, active_keys


def _mark_stale_scoped(
    active_keys: set,
    now: datetime,
    company_id: Optional[int] = None,
    field_ids: Optional[Sequence[int]] = None,
    product_ids: Optional[Sequence[int]] = None,
) -> int:
    """
    Позначає 'stale' лише ті рядки, що входять у задану область фільтрів.
    Якщо фільтри не вказані — працює по всій таблиці (як раніше).
    Порівняння виконується за ключем (field_id, product_id).
    """
    qry = PayerAllocation.query.filter(PayerAllocation.status != "stale")
    if company_id:
        qry = qry.filter(PayerAllocation.company_id == company_id)
    if field_ids:
        qry = qry.filter(PayerAllocation.field_id.in_(list(field_ids)))
    if product_ids:
        qry = qry.filter(PayerAllocation.product_id.in_(list(product_ids)))

    marked = 0
    for row in qry.all():
        key = AggKey(row.field_id, row.product_id)
        if key not in active_keys:
            row.status = "stale"
            row.updated_at = now
            marked += 1
    return marked



# ----------------------------- публічні API -----------------------------

def sync_from_plans(
    *,
    company_id: Optional[int] = None,
    field_ids: Optional[Sequence[int]] = None,
    product_ids: Optional[Sequence[int]] = None,
    only_approved_in_plain: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Повна синхронізація payer_allocations із (Approved)Plan/Treatment.
    Працює без імпорту ORM-класів Field/Product.
    """
    # 1) Будуємо запит і тягнемо плани
    q = _build_plans_query(
        only_approved_in_plain=only_approved_in_plain,
        company_id=company_id,
        field_ids=field_ids,
        product_ids=product_ids,
    )
    plan_rows = q.all()

    # 2) Агрегація
    agg_map, pids = _aggregate_rows(plan_rows)

    # 3) Метадані продуктів (manufacturer_id, unit_id)
    products_meta = _load_products_meta(pids)

    # 4) Upsert
    now = datetime.utcnow()
    added, updated, active_keys = _upsert_allocations(agg_map, products_meta, now)

    # 5) Позначити застарілі
    marked_stale = _mark_stale(active_keys, now)

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    # 6) Підрахунок активних
    total_active = PayerAllocation.query.filter_by(status="active").count()

    return {
        "added": added,
        "updated": updated,
        "marked_stale": marked_stale,
        "total_active": total_active,
    }


def sync_single_field(field_id: int, *, dry_run: bool = False) -> dict:
    """Синк лише одного поля."""
    return sync_from_plans(field_ids=[field_id], dry_run=dry_run)


def recompute_row_qty(field_id: int, product_id: int, *, commit: bool = True) -> Optional[float]:
    """
    Перерахунок qty для конкретної пари (field_id, product_id).
    """
    q = _build_plans_query(field_ids=[field_id], product_ids=[product_id])
    rows = q.all()
    if not rows:
        return None

    new_qty = float(sum(float(r.qty or 0.0) for r in rows))

    row = PayerAllocation.query.filter_by(field_id=field_id, product_id=product_id).first()
    now = datetime.utcnow()

    if row:
        row.qty = new_qty
        row.status = "active"
        row.updated_at = now
    else:
        # company_id з таблиці fields
        fields_t = _get_table("fields")
        comp = db.session.query(fields_t.c.company_id).filter(fields_t.c.id == field_id).first()
        comp_id = int(comp.company_id) if comp and comp.company_id is not None else None

        # метадані продукту
        meta = _load_products_meta([product_id]).get(product_id, {})
        manufacturer_id = meta.get("manufacturer_id")
        unit_id = meta.get("unit_id")

        db.session.add(PayerAllocation(
            field_id=field_id,
            company_id=comp_id,
            product_id=product_id,
            manufacturer_id=manufacturer_id,
            unit_id=unit_id,
            qty=new_qty,
            status="active",
            created_at=now,
            updated_at=now,
        ))

    if commit:
        db.session.commit()

    return new_qty


# ----------------------------- консолідація та “замовлено” -----------------------------

def get_already_ordered_map(
    *,
    company_id: Optional[int] = None,
    product_ids: Optional[Sequence[int]] = None,
    payer_ids: Optional[Sequence[int]] = None,
) -> Dict[Tuple[int, int, Optional[int]], float]:
    """
    {(company_id, product_id, payer_id): already_qty} з «Проплат».

    Джерело: PaymentInbox.items_json — список елементів виду:
      { "product_id": int, "payer_id": int|null, "qty": float, ... }

    Ігноруємо записи зі статусами з EXCLUDED.
    """
    # ледачий імпорт, щоб уникнути циклічних залежностей
    from modules.purchases.payments.models import PaymentInbox  # type: ignore

    q = PaymentInbox.query
    if company_id:
        q = q.filter(PaymentInbox.company_id == company_id)

    EXCLUDED = {"cancelled", "canceled", "rejected", "void", "deleted", "draft"}
    try:
        q = q.filter(~PaymentInbox.status.in_(list(EXCLUDED)))
    except Exception:
        pass  # якщо немає поля status

    rows = q.all()

    want_products = set(product_ids) if product_ids else None
    want_payers   = set(payer_ids) if payer_ids else None

    acc: Dict[Tuple[int, int, Optional[int]], float] = {}
    for inbox in rows:
        items = getattr(inbox, "items_json", None)
        if items is None:
            continue
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                continue
        if not isinstance(items, list):
            continue

        for it in items:
            # product_id (підтримує альтернативні ключі)
            pid = it.get("product_id") or it.get("product") or it.get("productId")
            try:
                pid = int(pid)
            except Exception:
                continue
            if want_products and pid not in want_products:
                continue

            # payer_id (може бути None; підтримує альтернативні ключі)
            pay = it.get("payer_id") or it.get("payer") or it.get("payerId")
            try:
                pay = int(pay) if pay is not None else None
            except Exception:
                pay = None
            if want_payers and pay not in want_payers:
                continue

            # qty (fallback на requested_qty)
            qty = it.get("qty", it.get("requested_qty", 0.0))
            try:
                qty = float(qty or 0.0)
            except Exception:
                qty = 0.0

            key = (inbox.company_id, pid, pay)
            acc[key] = acc.get(key, 0.0) + qty

    return acc



def get_consolidated_with_remaining(
    *,
    company_id: Optional[int] = None,
    product_id: Optional[int] = None,
    manufacturer_id: Optional[int] = None,
    payer_id: Optional[int] = None,
) -> List[dict]:
    """
    Консолідація активних рядків із total_qty, already_ordered_qty, remaining_qty
    + ПІДСТАНОВА НАЗВ: company_name, product_name, manufacturer_name, unit_name, payer_name
    + АЛІАСИ: qty_total, qty_already, qty_remaining.
    """
    q = (
        db.session.query(
            PayerAllocation.company_id,
            PayerAllocation.product_id,
            PayerAllocation.manufacturer_id,
            PayerAllocation.unit_id,
            PayerAllocation.payer_id,
            func.sum(PayerAllocation.qty).label("total_qty"),
        )
        .filter(PayerAllocation.status == "active")
        .group_by(
            PayerAllocation.company_id,
            PayerAllocation.product_id,
            PayerAllocation.manufacturer_id,
            PayerAllocation.unit_id,
            PayerAllocation.payer_id,
        )
    )

    if company_id:
        q = q.filter(PayerAllocation.company_id == company_id)
    if product_id:
        q = q.filter(PayerAllocation.product_id == product_id)
    if manufacturer_id:
        q = q.filter(PayerAllocation.manufacturer_id == manufacturer_id)
    if payer_id is not None:
        q = q.filter(PayerAllocation.payer_id == payer_id)

    rows = q.all()
    if not rows:
        return []

    # Звузимо множини для підрахунку already_ordered
    prod_set  = {int(r.product_id) for r in rows}
    payer_set = {int(r.payer_id) for r in rows if r.payer_id is not None}

    # already_ordered по (company_id, product_id, payer_id)
    ordered_map = get_already_ordered_map(
        company_id=company_id,                                   # може бути None → по всіх компаніях
        product_ids=list(prod_set) if prod_set else None,        # звужуємо до наявних продуктів
        payer_ids=list(payer_set) if payer_set else None,        # і до наявних платників
    )

    result: List[dict] = []
    for r in rows:
        total = float(r.total_qty or 0.0)
        already = float(ordered_map.get((r.company_id, r.product_id, r.payer_id), 0.0))
        remaining = max(total - already, 0.0)
        result.append({
            "company_id": r.company_id,
            "product_id": r.product_id,
            "manufacturer_id": r.manufacturer_id,
            "unit_id": r.unit_id,
            "payer_id": r.payer_id,
            "total_qty": total,
            "already_ordered_qty": already,
            "remaining_qty": remaining,
            "qty_total": total,
            "qty_already": already,
            "qty_remaining": remaining,
        })

    # Підстановка назв/тари
    comp_ids  = {row["company_id"]      for row in result if row.get("company_id") is not None}
    prod_ids  = {row["product_id"]      for row in result if row.get("product_id") is not None}
    man_ids   = {row["manufacturer_id"] for row in result if row.get("manufacturer_id") is not None}
    unit_ids  = {row["unit_id"]         for row in result if row.get("unit_id") is not None}
    payer_ids = {row["payer_id"]        for row in result if row.get("payer_id") is not None}

    cmap   = _fetch_names("companies", comp_ids)
    pmap   = _fetch_names("products", prod_ids)
    umap   = _fetch_names("units", unit_ids)
    paymap = _fetch_names("payers", payer_ids)

    mfg_names = {}
    if man_ids:
        mfg_names = _fetch_names("manufacturers", man_ids) or _fetch_names("producers", man_ids)

    prod_mfg_txt = _fetch_product_manufacturer_name(prod_ids)
    pkgmap       = _fetch_product_package(prod_ids)

    for row in result:
        row["company_name"] = cmap.get(row.get("company_id"), "—")
        row["product_name"] = pmap.get(row.get("product_id"), "—")
        row["unit_name"]    = umap.get(row.get("unit_id"), "—")
        row["payer_name"]   = paymap.get(row.get("payer_id"), "—") if row.get("payer_id") is not None else "—"

        mid = row.get("manufacturer_id")
        row["manufacturer_name"] = mfg_names.get(mid) if mid is not None else None
        if not row["manufacturer_name"]:
            row["manufacturer_name"] = prod_mfg_txt.get(row.get("product_id")) or "—"

        row["package"] = pkgmap.get(row.get("product_id")) or "—"

    return result




# --- Backward-compat helper (старий інтерфейс) -------------------------------------

def get_consolidated_allocations(
    *,
    company_id: Optional[int] = None,
    product_id: Optional[int] = None,
    manufacturer_id: Optional[int] = None,
    payer_id: Optional[int] = None,
) -> List[dict]:
    """
    Сумісний зі старим кодом API:
      [{company_id, product_id, manufacturer_id, unit_id, total_qty}, ...]
    Під капотом використовує get_consolidated_with_remaining(...).
    """
    rows = get_consolidated_with_remaining(
        company_id=company_id,
        product_id=product_id,
        manufacturer_id=manufacturer_id,
        payer_id=payer_id,
    )
    return [
        {
            "company_id": r["company_id"],
            "product_id": r["product_id"],
            "manufacturer_id": r["manufacturer_id"],
            "unit_id": r["unit_id"],
            "total_qty": r["total_qty"],
        }
        for r in rows
    ]
def reconcile_allocations_against_plans(
    *,
    company_id: Optional[int] = None,
    field_ids: Optional[Sequence[int]] = None,
    product_ids: Optional[Sequence[int]] = None,
    only_approved_in_plain: bool = True,
) -> int:
    """
    Звіряє payer_allocations із (Approved)Plan/Treatment і позначає зайві рядки як 'stale'.
    Працює в заданій області (компанія/поля/продукти) — решту не чіпає.

    Повертає кількість позначених 'stale'.
    """
    # 1) які (field_id, product_id) реально присутні у планах зараз
    q = _build_plans_query(
        only_approved_in_plain=only_approved_in_plain,
        company_id=company_id,
        field_ids=field_ids,
        product_ids=product_ids,
    )
    plan_rows = q.all()
    active_keys = {AggKey(int(r.field_id), int(r.product_id)) for r in plan_rows}

    # 2) пробігаємось лише по релевантних снапшотах і, якщо ключа нема у планах — ставимо 'stale'
    qry = PayerAllocation.query.filter(PayerAllocation.status != "stale")
    if company_id:
        qry = qry.filter(PayerAllocation.company_id == company_id)
    if field_ids:
        qry = qry.filter(PayerAllocation.field_id.in_(list(field_ids)))
    if product_ids:
        qry = qry.filter(PayerAllocation.product_id.in_(list(product_ids)))

    now = datetime.utcnow()
    marked = 0
    for row in qry.all():
        key = AggKey(row.field_id, row.product_id)
        if key not in active_keys:
            row.status = "stale"
            row.updated_at = now
            marked += 1

    if marked:
        db.session.commit()
    return marked
def _mark_stale_scoped(
    active_keys: set,
    now: datetime,
    company_id: Optional[int] = None,
    field_ids: Optional[Sequence[int]] = None,
    product_ids: Optional[Sequence[int]] = None,
) -> int:
    """
    Позначає 'stale' лише для рядків у межах заданих фільтрів.
    Якщо фільтри не задані — працює по всій таблиці.
    """
    qry = PayerAllocation.query.filter(PayerAllocation.status != "stale")
    if company_id:
        qry = qry.filter(PayerAllocation.company_id == company_id)
    if field_ids:
        qry = qry.filter(PayerAllocation.field_id.in_(list(field_ids)))
    if product_ids:
        qry = qry.filter(PayerAllocation.product_id.in_(list(product_ids)))

    marked = 0
    for row in qry.all():
        key = AggKey(row.field_id, row.product_id)
        if key not in active_keys:
            row.status = "stale"
            row.updated_at = now
            marked += 1
    return marked


# ↓ Зворотна сумісність: старі виклики _mark_stale(active_keys, now) продовжують працювати
def _mark_stale(active_keys: set, now: datetime) -> int:
    return _mark_stale_scoped(active_keys, now)

