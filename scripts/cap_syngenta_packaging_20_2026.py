"""One-time correction: choose largest evidenced Syngenta package <= 20 L/kg.

Only the eight industrial-package rows are updated. All other products,
chemical data, current business records and source history are untouched.
Each change is backed up in the SAME transaction; never runs without an
explicit short-lived Render environment flag.
"""
import json
import os
import re
from pathlib import Path

from flask import current_app
from sqlalchemy import text
from extensions import db

FLAG = "AGROERP_CAP_SYNGENTA_PACKAGING_20_ONCE"
VALUE = "APPLY_8_VERIFIED_PACKAGING_CORRECTIONS_2026_11_18"
KEY = "syngenta_package_cap20_2026_11_18_v1"
DATA = Path(__file__).parents[1] / "modules/reference/products/syngenta_packaging_cap20_2026.json"
CURRENT_SOURCE = Path(__file__).parents[1] / "modules/reference/products/syngenta_packaging_2026.json"
PACK = re.compile(r"^(\\d+(?:,\\d+)?) (л|кг)$")


def _size(raw):
    m = PACK.fullmatch(raw)
    if not m:
        raise ValueError(f"Unsupported package format: {raw}")
    return float(m.group(1).replace(",", ".")), m.group(2)


def validate_corrections(change, original, observed):
    """Fail closed if source or any live product differs from our baseline."""
    entries = change["entries"]
    if len(entries) != 8 or len(observed) != 108 or len(original["entries"]) != 108:
        raise ValueError("Unexpected original catalog or correction counts")
    prior_by_id = {int(e["index"]) + 52: e for e in original["entries"]}
    live_by_id = {int(e["id"]): e for e in observed}
    if set(live_by_id) != set(range(53, 161)):
        raise ValueError("Missing or unexpected live Syngenta product")
    if any(e["is_archived"] for e in observed):
        raise ValueError("Unexpected archived product")
    if set(e["id"] for e in entries) != {99, 108, 111, 114, 115, 119, 122, 126}:
        raise ValueError("Correction IDs do not match expected eight")
    changed_ids = set()
    for e in entries:
        pid = int(e["id"])
        original_entry = prior_by_id[pid]
        live = live_by_id[pid]
        if (e["index"] + 52 != pid
            or original_entry["name"] != e["name"]
            or live["name"] != e["name"]
            or original_entry["container"] != e["old"]
            or live["container"] != e["old"]):
            raise ValueError(f"Unexpected product identity or previous package {pid}")
        old_size, old_unit = _size(e["old"])
        new_size, new_unit = _size(e["next"])
        if old_size <= 20 or new_size > 20 or new_size <= 0 or old_unit != new_unit:
            raise ValueError(f"Invalid max-20 change for {pid}")
        opts = e["verified_options"]
        eligible = [_size(x)[0] for x in opts if _size(x)[1] == new_unit and _size(x)[0] <= 20]
        if not eligible or new_size != max(eligible):
            raise ValueError(f"New packaging not the largest evidenced under 20 for {pid}")
        if not e.get("source", "").startswith("https://"):
            raise ValueError("No source URL for corrected package")
        changed_ids.add(pid)
    if len(changed_ids) != 8:
        raise ValueError("Duplicate correction IDs")
    for pid, row in live_by_id.items():
        if pid in changed_ids:
            continue
        old = prior_by_id[pid]
        if old["name"] != row["name"] or old["container"] != row["container"]:
            raise ValueError(f"Unrelated product {pid} modified since original backfill")
        size, _ = _size(row["container"])
        if size > 20:
            raise ValueError(f"Uncovered oversized product {pid}")


def run_once():
    if os.getenv(FLAG) != VALUE:
        return {"status": "not_requested"}
    if db.engine.dialect.name != "postgresql":
        return {"status": "unsupported_engine"}

    try:
        change = json.loads(DATA.read_text(encoding="utf-8"))
        original = json.loads(CURRENT_SOURCE.read_text(encoding="utf-8"))
        with db.engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '15s'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(381546, 20261118)"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.agroerp_packaging_cap20_audit (
                    operation_key text PRIMARY KEY,
                    executed_at timestamptz NOT NULL DEFAULT current_timestamp,
                    payload jsonb NOT NULL
                )
            """))
            if conn.execute(text("""
                SELECT EXISTS(SELECT 1 FROM agroerp_packaging_cap20_audit
                    WHERE operation_key = :key)
            """), {"key": KEY}).scalar_one():
                return {"status": "already_executed"}

            conn.execute(text("LOCK TABLE public.products IN SHARE ROW EXCLUSIVE MODE"))
            observed = [dict(r) for r in conn.execute(text("""
                SELECT id, name, container, is_archived
                FROM public.products ORDER BY id
            """)).mappings()]
            validate_corrections(change, original, observed)
            audit = json.dumps({
                "selection_rule": change["selection_rule"],
                "before": observed,
                "corrections": change["entries"],
            }, ensure_ascii=False)
            conn.execute(text("""
                INSERT INTO public.agroerp_packaging_cap20_audit
                    (operation_key, payload)
                VALUES (:key, CAST(:payload AS jsonb))
            """), {"key": KEY, "payload": audit})

            changed = 0
            for e in change["entries"]:
                changed += conn.execute(text("""
                    UPDATE public.products
                    SET container = :new
                    WHERE id=:id AND name=:name AND container=:old
                      AND is_archived=false
                """), {
                    "id": e["id"], "name": e["name"],
                    "old": e["old"], "new": e["next"],
                }).rowcount
            if changed != 8:
                raise RuntimeError(f"Rolled back: expected eight rows, got {changed}")

            final = [dict(r) for r in conn.execute(text("""
                SELECT id, name, container, is_archived FROM public.products ORDER BY id
            """)).mappings()]
            corrections_by_id = {e["id"]: e["next"] for e in change["entries"]}
            before_by_id = {r["id"]: r for r in observed}
            for row in final:
                expected = corrections_by_id.get(row["id"], before_by_id[row["id"]]["container"])
                if row["container"] != expected or _size(row["container"])[0] > 20:
                    raise RuntimeError("Rolled back: unexpected final packaging values")
            return {"status": "completed", "updated": changed, "total_products": 108}
    except Exception:
        current_app.logger.exception("Syngenta cap-20 packaging update failed; rolled back")
        return {"status": "failed_rolled_back"}
