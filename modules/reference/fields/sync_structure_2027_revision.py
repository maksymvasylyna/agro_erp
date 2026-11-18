"""Guarded one-shot reconciliation of the 2027 field structure (18 Nov 2026).

The full previous and revised snapshots are retained in Git for audit.
Mutate only eight changed 2027 crop areas and remove the three absent
2027 seasonal records. Permanent dictionary fields and other years stay.
"""
import json
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from extensions import db
from modules.reference.fields.import_structure_2027 import _source, CULTURE_ALIASES

ENV_NAME = "AGROERP_SYNC_2027_REVISION_ONCE"
ENV_TOKEN = "APPLY_VERIFIED_2027_REVISION_2026_11_18"
OPERATION = "structure_2027_revision_2026_11_18"
EXPECTED_REMOVED = {"ПЧ1 025/2", "ППО 026", "ЧК1 011/2"}
EXPECTED_UPDATED = {
    "ГЗО 018": ("41.72", "32.64"),
    "ЧК1 007": ("67.50", "65.50"),
    "ЧК1 008": ("33.45", "30.85"),
    "ЧК1 009": ("66.05", "68.75"),
    "ЧК1 010": ("56.00", "61.00"),
    "ЧК1 012": ("7.00", "10.20"),
    "ЧК2 009": ("53.13", "50.18"),
    "ЧК3 006": ("7.00", "7.70"),
}
OLD_TOTAL = Decimal("34238.87")
NEW_TOTAL = Decimal("34142.59")


def _row_map(rows):
    result = {}
    for item in rows:
        key = item["field"]
        if key in result or not item["company"] or not item["culture"]:
            raise ValueError("Invalid/duplicate source field: " + key)
        area = Decimal(item["area"])
        if area <= 0 or area != area.quantize(Decimal("0.01")):
            raise ValueError("Invalid source area for field: " + key)
        result[key] = item
    return result


def _revision():
    filename = Path(__file__).parent / "import_data" / "structure_2027_revision_2026_11_18.json"
    payload = json.loads(filename.read_text(encoding="utf-8"))
    if payload["season"] != 2027 or payload["row_count"] != 544:
        raise RuntimeError("2027 revision header/row count changed")
    old = _row_map(_source())
    new = _row_map(payload["rows"])
    if len(old) != 547 or len(new) != 544:
        raise RuntimeError("Unexpected number of revision records")

    total_old = sum((Decimal(x["area"]) for x in old.values()), Decimal("0.00"))
    total_new = sum((Decimal(x["area"]) for x in new.values()), Decimal("0.00"))
    if total_old != OLD_TOTAL or total_new != NEW_TOTAL:
        raise RuntimeError("2027 revision control totals do not match the source")

    removed = set(old) - set(new)
    added = set(new) - set(old)
    updated = {
        field for field in set(old) & set(new)
        if old[field]["area"] != new[field]["area"]
        or old[field]["company"] != new[field]["company"]
        or old[field]["culture"] != new[field]["culture"]
    }
    if removed != EXPECTED_REMOVED or added or updated != set(EXPECTED_UPDATED):
        raise RuntimeError("Unexpected field changes in 2027 revision")
    for field, (before, after) in EXPECTED_UPDATED.items():
        if old[field]["area"] != before or new[field]["area"] != after:
            raise RuntimeError("Unexpected revised area for " + field)
        if (old[field]["company"] != new[field]["company"]
                or old[field]["culture"] != new[field]["culture"]):
            raise RuntimeError("Unexpected ownership/crop change for " + field)
    return old, new


def apply_revision():
    """All-or-nothing year-specific sync, verified before and after writes."""
    old, new = _revision()
    with db.engine.begin() as conn:
        if db.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(2027, 547)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agroerp_structure_revisions (
                operation_key text PRIMARY KEY,
                season_year integer NOT NULL,
                before_count integer NOT NULL,
                after_count integer NOT NULL,
                before_area text NOT NULL,
                after_area text NOT NULL,
                details text NOT NULL,
                created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        if conn.execute(text("""
            SELECT 1 FROM agroerp_structure_revisions WHERE operation_key=:key
        """), {"key": OPERATION}).first():
            return {"already_applied": True}

        season = conn.execute(text("""
            SELECT id, is_closed FROM seasons WHERE year=2027
        """)).mappings().one_or_none()
        if not season or season["is_closed"]:
            raise RuntimeError("Cannot reconcile missing/closed 2027 season")

        if not conn.execute(text("""
            SELECT 1 FROM agroerp_structure_corrections
            WHERE operation_key='correct_2027_MT0_002_MT1_002_2026_11_17'
        """)).first():
            raise RuntimeError("The previous full 2027 correction is not installed")

        def existing_records():
            return conn.execute(text("""
                SELECT fs.id AS record_id,fs.field_id,fs.area AS field_area,
                       f.name AS field,c.name AS company,
                       fp.id AS planting_id,fp.area AS planted_area,
                       cu.name AS culture
                FROM field_seasons fs
                JOIN fields f ON f.id=fs.field_id
                JOIN companies c ON c.id=fs.company_id
                LEFT JOIN field_plantings fp ON fp.field_season_id=fs.id
                LEFT JOIN cultures cu ON cu.id=fp.culture_id
                WHERE fs.season_id=:season ORDER BY f.name,fp.id
            """), {"season": season["id"]}).mappings().all()

        before = existing_records()
        if len(before) != 547 or len({r["field"] for r in before}) != 547:
            raise RuntimeError("2027 database has changed field/planting cardinality")

        by_field = {r["field"]: r for r in before}
        if set(by_field) != set(old):
            raise RuntimeError("2027 database field list differs from baseline source")

        def check_record(record, source):
            return (
                record["planting_id"] is not None
                and record["company"] == source["company"]
                and record["culture"] == CULTURE_ALIASES.get(
                    source["culture"], source["culture"]
                )
                and Decimal(str(record["field_area"])) == Decimal(source["area"])
                and Decimal(str(record["planted_area"])) == Decimal(source["area"])
            )

        for name, entry in old.items():
            if not check_record(by_field[name], entry):
                raise RuntimeError("2027 database diverged from prior snapshot at " + name)

        actions = []
        for field in sorted(EXPECTED_UPDATED):
            entry = new[field]
            record = by_field[field]
            area = entry["area"]
            first = conn.execute(text("""
                UPDATE field_seasons SET area=:area
                WHERE id=:id AND season_id=:season
            """), {"area": area, "id": record["record_id"], "season": season["id"]})
            second = conn.execute(text("""
                UPDATE field_plantings SET area=:area
                WHERE id=:id AND field_season_id=:record
            """), {"area": area, "id": record["planting_id"], "record": record["record_id"]})
            if first.rowcount != 1 or second.rowcount != 1:
                raise RuntimeError("Unexpected area update count for " + field)
            actions.append({
                "action": "area", "field": field,
                "before": old[field]["area"], "after": area,
            })

        for field in sorted(EXPECTED_REMOVED):
            record = by_field[field]
            # A field is removed only from the 2027 season, never the directory.
            dependent_plans = conn.execute(text("""
                SELECT COUNT(*) FROM plans WHERE season_id=:season AND field_id=:field
            """), {"season": season["id"], "field": record["field_id"]}).scalar_one()
            if dependent_plans:
                raise RuntimeError("Cannot remove 2027 field referenced by a plan: " + field)
            deleted_planting = conn.execute(text("""
                DELETE FROM field_plantings
                WHERE id=:id AND field_season_id=:record
            """), {"id": record["planting_id"], "record": record["record_id"]})
            deleted_season = conn.execute(text("""
                DELETE FROM field_seasons
                WHERE id=:record AND season_id=:season
            """), {"record": record["record_id"], "season": season["id"]})
            if deleted_planting.rowcount != 1 or deleted_season.rowcount != 1:
                raise RuntimeError("Unexpected row count while removing " + field)
            actions.append({
                "action": "remove_from_2027", "field": field,
                "before": old[field]["area"],
            })

        after = existing_records()
        if len(after) != 544 or len({r["field"] for r in after}) != 544:
            raise RuntimeError("2027 reconciliation failed row-count control")
        after_by_field = {r["field"]: r for r in after}
        if set(after_by_field) != set(new):
            raise RuntimeError("2027 reconciliation failed field membership control")
        for field, source in new.items():
            if not check_record(after_by_field[field], source):
                raise RuntimeError("2027 post-import field mismatch: " + field)
        after_area = sum(
            (Decimal(str(row["planted_area"])) for row in after),
            Decimal("0.00"),
        )
        if after_area != NEW_TOTAL:
            raise RuntimeError("2027 post-import area total failed")

        conn.execute(text("""
            INSERT INTO agroerp_structure_revisions
              (operation_key,season_year,before_count,after_count,
               before_area,after_area,details)
            VALUES (:key,2027,547,544,:before,:after,:details)
        """), {
            "key": OPERATION, "before": str(OLD_TOTAL), "after": str(NEW_TOTAL),
            "details": json.dumps(actions, ensure_ascii=False),
        })
        return {
            "updated": len(EXPECTED_UPDATED),
            "removed_from_2027": len(EXPECTED_REMOVED),
            "fields": len(after),
            "area_ha": str(after_area),
        }


def apply_if_requested():
    if os.getenv(ENV_NAME) != ENV_TOKEN:
        return
    result = apply_revision()
    print("AgroERP 2027 revision:", result, flush=True)
