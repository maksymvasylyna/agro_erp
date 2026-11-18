"""Additive schema upgrade and audited, one-time Syngenta pilot import.

No product is represented as registration-approved: source catalog alone is
not the current Ukrainian state register. Linked historical IDs are preserved.
"""
import json
import os
import re
from pathlib import Path

from flask import current_app
from sqlalchemy import func, text

from extensions import db
from modules.reference.categories.models import Category
from modules.reference.groups.models import Group
from modules.reference.manufacturers.models import Manufacturer
from modules.reference.units.models import Unit
from .models import Product, ProductIngredient, ActiveIngredient

FLAG = "AGROERP_IMPORT_SYNGENTA_2026_ONCE"
FLAG_VALUE = "IMPORT_108_UNVERIFIED_SYNGENTA_ITEMS_2026_11_18"
IMPORT_KEY = "syngenta_ua_catalog_2026_11_18_v1"
SOURCE = Path(__file__).with_name("syngenta_catalog_2026.json")

CATEGORY = {
    "Інсектицид": ("Інсектециди", "Засоби захисту рослин"),
    "Гербіцид": ("Гербіциди", "Засоби захисту рослин"),
    "Фунгіцид": ("Фунгіциди", "Засоби захисту рослин"),
    "Протруйник комбінований": ("Протравники", "Засоби захисту рослин"),
    "Протруйник фунгіцидний": ("Протравники", "Засоби захисту рослин"),
    "Протруйник інсектицидний": ("Протравники", "Засоби захисту рослин"),
    "Регулятор росту / ретардант": ("Морфорегулятори", "Засоби захисту рослин"),
    "Родентицид": ("Родентициди", "Засоби захисту рослин"),
    "Біофунгіцид": ("Біофунгіциди", "Біологічні продукти"),
    "Інокулянт": ("Інокулянти", "Біологічні продукти"),
    "Біостимулятор / мікродобриво":
        ("Біостимулятори та мікродобрива", "Коректори живлення"),
}
SOLID = {"WG", "GR", "SG", "WP", "RB"}
LIQUID = {"EC", "SC", "FS", "SL", "SE", "DC", "OD", "ZC", "CS", "ES", "РК"}
CONCENTRATION = re.compile(
    r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*(г/л|г/кг|мг/л|мг/кг|%)\s*$",
    flags=re.IGNORECASE,
)


def ensure_schema():
    """Idempotent, additive PostgreSQL migration; never deletes master data."""
    if db.engine.dialect.name != "postgresql":
        return
    types = {
        "formulation_code": "varchar(32)",
        "formulation_name": "varchar(160)",
        "composition": "text",
        "registration_status": "varchar(80)",
        "registration_number": "varchar(120)",
        "registration_valid_until": "date",
        "source_url": "text",
        "source_note": "text",
        "is_archived": "boolean NOT NULL DEFAULT false",
    }
    with db.engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(381529, 20261118)"))
        for field, sql_type in types.items():
            conn.execute(text(
                f"ALTER TABLE public.products ADD COLUMN IF NOT EXISTS {field} {sql_type}"
            ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.agroerp_product_imports (
                operation_key text PRIMARY KEY,
                executed_at timestamptz NOT NULL DEFAULT current_timestamp,
                old_products jsonb NOT NULL,
                archived_count integer NOT NULL,
                inserted_count integer NOT NULL
            )
        """))


def sync_components(product, composition):
    """Split source string into product-to-substance rows without inventing doses.

    Unspecified amounts remain NULL. Safeners are marked explicitly; numeric
    concentrations are parsed only when a unit is given in source text.
    """
    product.components.clear()
    db.session.flush()
    for fragment in (composition or "").split(";"):
        fragment = fragment.strip()
        if not fragment:
            continue
        match = CONCENTRATION.match(fragment)
        name = match.group(1).strip() if match else fragment
        if not name:
            continue
        ingredient = ActiveIngredient.query.filter(
            func.lower(ActiveIngredient.name) == name.lower()
        ).first()
        if ingredient is None:
            ingredient = ActiveIngredient(name=name)
            db.session.add(ingredient)
            db.session.flush()
        product.components.append(ProductIngredient(
            ingredient=ingredient,
            concentration_value=float(match.group(2).replace(",", ".")) if match else None,
            concentration_unit=match.group(3).lower() if match else None,
            is_safener=("антидот" in name.casefold()),
        ))


def import_if_requested():
    """Explicit one-time import via Render flag; idempotent across workers."""
    if os.getenv(FLAG) != FLAG_VALUE:
        return {"status": "not_requested"}
    if db.engine.dialect.name != "postgresql":
        return {"status": "non_postgres_noop"}
    try:
        payload = json.loads(SOURCE.read_text(encoding="utf-8"))
        items = payload["products"]
        if len(items) != 108 or len({p["name"].casefold() for p in items}) != 108:
            return {"status": "invalid_source_count_or_duplicate"}
        db.session.execute(text("SELECT pg_advisory_xact_lock(381529, 20261119)"))
        already = db.session.execute(text("""
            SELECT 1 FROM public.agroerp_product_imports
            WHERE operation_key = :key
        """), {"key": IMPORT_KEY}).scalar()
        if already:
            db.session.rollback()
            return {"status": "already_imported"}

        old_count = Product.query.count()
        # Verified baseline 18 Nov 2026. Never archive unexpected new records.
        if old_count != 49:
            db.session.rollback()
            current_app.logger.warning(
                "Syngenta import skipped: expected 49 products, got %s", old_count
            )
            return {"status": "count_guard", "found": old_count}
        snapshot = db.session.execute(text(
            "SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.id), '[]'::jsonb) "
            "FROM public.products AS p"
        )).scalar()
        # Keep historical IDs referenced by purchasing, shipment requests, etc.
        Product.query.update({Product.is_archived: True}, synchronize_session=False)

        syngenta = Manufacturer.query.filter(
            func.lower(Manufacturer.name) == "syngenta"
        ).first()
        if syngenta is None:
            syngenta = Manufacturer(name="Syngenta")
            db.session.add(syngenta)
            db.session.flush()

        category_cache = {c.name: c for c in Category.query.all()}
        group_cache = {g.name: g for g in Group.query.all()}
        unit_cache = {u.name: u for u in Unit.query.all()}

        def get_reference(cache, model, name):
            if name not in cache:
                obj = model(name=name)
                db.session.add(obj)
                db.session.flush()
                cache[name] = obj
            return cache[name]

        for item in items:
            group_label = item["type"]
            if group_label not in CATEGORY:
                raise ValueError(f"Unsupported Syngenta category: {group_label}")
            category_name, general_group = CATEGORY[group_label]
            code = item["formulation_code"]
            unit_name = ("кг" if code in SOLID
                         else "л" if code in LIQUID else None)
            product = Product(
                name=item["name"].strip(),
                manufacturer_id=syngenta.id,
                category_id=get_reference(category_cache, Category, category_name).id,
                group_id=get_reference(group_cache, Group, general_group).id,
                unit_id=unit_cache[unit_name].id if unit_name in unit_cache else None,
                container=None,  # Packaging is NOT formulation; never guess it.
                formulation_code=code,
                formulation_name=item["formulation_name"],
                composition=item["composition"],
                registration_status="Потребує звірки з Держреєстром",
                registration_number=None,
                registration_valid_until=None,
                source_url=item["source_url"],
                source_note=item["source_note"],
                is_archived=False,
            )
            db.session.add(product)
            db.session.flush()
            sync_components(product, product.composition)

        # Save full old product snapshot in production DB before marking import done.
        db.session.execute(text("""
            INSERT INTO public.agroerp_product_imports
                (operation_key, old_products, archived_count, inserted_count)
            VALUES (:key, CAST(:snapshot AS jsonb), :archived, :inserted)
        """), {
            "key": IMPORT_KEY, "snapshot": json.dumps(snapshot, ensure_ascii=False)
            if isinstance(snapshot, (dict, list)) else str(snapshot),
            "archived": old_count, "inserted": len(items),
        })
        db.session.commit()
        return {"status": "imported", "old_archived": old_count, "new": len(items)}
    except Exception:
        db.session.rollback()
        current_app.logger.exception("One-time Syngenta catalog import failed")
        return {"status": "error"}
