"""Audited one-time update of largest documented Syngenta package sizes.

No product is created/deleted. An exact-ID/name guard protects the directory;
existing packaging must be blank. The transactional backup records old and
new values and source references before any updates are committed.
"""
import json
import os
import re
from pathlib import Path

from flask import current_app
from sqlalchemy import text

from extensions import db

FLAG = "AGROERP_BACKFILL_SYNGENTA_PACKAGING_2026_ONCE"
VALUE = "SET_MAX_PACK_FOR_108_SYNGENTA_PRODUCTS_2026_11_18"
KEY = "syngenta_max_packaging_2026_11_18_v1"
DATA = Path(__file__).parents[1] / "modules/reference/products/syngenta_packaging_2026.json"
CATALOG = Path(__file__).parents[1] / "modules/reference/products/syngenta_catalog_2026.json"
FORMAT = re.compile(r"^\d+(?:,\d+)? (?:л|кг)$")


def validate_payload(packaging, catalog, observed):
    """Check all 108 exact product IDs/names and valid volume/weight units."""
    entries = packaging["entries"]
    names = [p["name"] for p in catalog["products"]]
    if len(entries) != 108 or len(names) != 108 or len(observed) != 108:
        raise ValueError("Expected 108 Syngenta catalog products and 108 live rows")
    if {item["index"] for item in entries} != set(range(1, 109)):
        raise ValueError("Packaging entries must cover product indices 1..108 exactly")
    for e in entries:
        i = e["index"]
        if names[i - 1] != e["name"]:
            raise ValueError(f"Product name mismatch at source index {i}")
        if not FORMAT.fullmatch(e["container"]):
            raise ValueError(f"Unexpected package format: {e['name']}")
    by_id = {row["id"]: row for row in observed}
    if set(by_id) != set(range(53, 161)):
        raise ValueError("Live product IDs differ from the verified 2026 import")
    for e in entries:
        row = by_id[e["index"] + 52]
        if row["name"] != e["name"] or row["is_archived"] or row["container"] is not None:
            raise ValueError(f"Live product changed or has packaging: {e['name']}")


def run_once():
    if os.environ.get(FLAG) != VALUE:
        return {"status": "not_requested"}
    if db.engine.dialect.name != "postgresql":
        return {"status": "unsupported_engine"}

    try:
        packaging = json.loads(DATA.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        with db.engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '15s'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(381544, 20261118)"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.agroerp_packaging_backfills (
                    operation_key text PRIMARY KEY,
                    executed_at timestamptz NOT NULL DEFAULT current_timestamp,
                    audit_json jsonb NOT NULL
                )
            """))
            if conn.execute(text("""
                SELECT EXISTS(SELECT 1 FROM agroerp_packaging_backfills
                  WHERE operation_key=:key)
            """), {"key": KEY}).scalar_one():
                return {"status": "already_executed"}

            conn.execute(text("LOCK TABLE public.products IN SHARE ROW EXCLUSIVE MODE"))
            observed = [dict(r) for r in conn.execute(text("""
                SELECT id, name, is_archived, container FROM public.products ORDER BY id
            """)).mappings()]
            validate_payload(packaging, catalog, observed)
            before = json.dumps({
                "source": packaging["primary_source_url"],
                "source_transcript": packaging["primary_source_transcript"],
                "secondary_source": packaging["secondary_source_url"],
                "rule": packaging["principle"],
                "old_rows": observed,
                "new_values": packaging["entries"],
            }, ensure_ascii=False)
            conn.execute(text("""
                INSERT INTO public.agroerp_packaging_backfills(operation_key, audit_json)
                VALUES (:key, CAST(:payload AS jsonb))
            """), {"key": KEY, "payload": before})

            changed = 0
            for e in packaging["entries"]:
                result = conn.execute(text("""
                    UPDATE public.products SET container=:container
                    WHERE id=:id AND name=:name AND is_archived=false
                      AND container IS NULL
                """), {
                    "id": e["index"] + 52,
                    "name": e["name"],
                    "container": e["container"],
                })
                changed += result.rowcount
            if changed != 108:
                raise RuntimeError(f"Expected 108 changed rows, got {changed}")
            final = conn.execute(text("""
                SELECT COUNT(*) AS total, COUNT(*) FILTER (
                    WHERE container IS NOT NULL AND NOT is_archived
                ) AS filled, COUNT(*) FILTER (WHERE is_archived) AS archived
                FROM public.products
            """)).mappings().one()
            if dict(final) != {"total": 108, "filled": 108, "archived": 0}:
                raise RuntimeError(f"Unexpected final product state: {dict(final)}")
            return {"status": "completed", "filled": changed}
    except Exception:
        current_app.logger.exception("Syngenta packaging update rolled back")
        return {"status": "failed_rolled_back"}
