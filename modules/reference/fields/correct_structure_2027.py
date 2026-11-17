"""One-shot, audited correction of two demo 2027 field records.

Only the season-level crop allocation and area of МТ0 002 and МТ1 002
are altered. The permanent fields dictionary and other seasons remain intact.
"""
import json
import os
from decimal import Decimal

from sqlalchemy import text

from extensions import db
from modules.reference.fields.import_structure_2027 import _source

ENV_NAME = "AGROERP_CORRECT_2027_TWO_DEMO_FIELDS_ONCE"
ENV_TOKEN = "MATCH_HISTORY_2027_TWO_TEST_FIELDS"
OPERATION = "correct_2027_MT0_002_MT1_002_2026_11_17"

# Guard against changing data that a user may have edited after inspection.
PREVIOUS = {
    "МТ0 002": {"area": Decimal("34.31"), "culture": "Горох зимуючий"},
    "МТ1 002": {"area": Decimal("60.00"), "culture": "Кукурудза на силос"},
}
EXPECTED_TOTAL_BEFORE = Decimal("34160.49")
EXPECTED_TOTAL_AFTER = Decimal("34238.87")


def correct_two_fields():
    source_rows = {
        row["field"]: row for row in _source()
        if row["field"] in PREVIOUS
    }
    if set(source_rows) != set(PREVIOUS):
        raise RuntimeError("Both field names must exist in the original 2027 source")

    with db.engine.begin() as conn:
        if db.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(2027, 547)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agroerp_structure_corrections (
                operation_key text PRIMARY KEY,
                season_year integer NOT NULL,
                before_details text NOT NULL,
                after_details text NOT NULL,
                created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        if conn.execute(text("""
            SELECT 1 FROM agroerp_structure_corrections
            WHERE operation_key=:key
        """), {"key": OPERATION}).first():
            return {"already_corrected": True}

        season = conn.execute(text("""
            SELECT id, is_closed FROM seasons WHERE year=2027
        """)).mappings().one()
        if season["is_closed"]:
            raise RuntimeError("2027 season is closed")

        imported = conn.execute(text("""
            SELECT 1 FROM agroerp_structure_imports
            WHERE operation_key='history_2027_547_fields_2026_11_17'
        """)).first()
        if imported is None:
            raise RuntimeError("Full 2027 import must exist before correction")

        structure = conn.execute(text("""
            SELECT COUNT(*) AS records, COALESCE(SUM(fp.area), 0) AS total_area
            FROM field_seasons fs
            JOIN field_plantings fp ON fp.field_season_id=fs.id
            WHERE fs.season_id=:season
        """), {"season": season["id"]}).mappings().one()
        if (structure["records"] != 547
                or Decimal(str(structure["total_area"])) != EXPECTED_TOTAL_BEFORE):
            raise RuntimeError("2027 structure has changed since the verified import")

        rows = conn.execute(text("""
            SELECT fs.id AS record_id, f.name AS name, fs.area AS field_area,
                   fs.company_id, fs.cluster_id,
                   co.name AS company_name,
                   fp.id AS planting_id, fp.area AS planted_area,
                   cu.name AS culture_name
            FROM field_seasons fs
            JOIN fields f ON f.id=fs.field_id
            JOIN companies co ON co.id=fs.company_id
            LEFT JOIN field_plantings fp ON fp.field_season_id=fs.id
            LEFT JOIN cultures cu ON cu.id=fp.culture_id
            WHERE fs.season_id=:season AND f.name IN ('МТ0 002', 'МТ1 002')
            ORDER BY f.name
        """), {"season": season["id"]}).mappings().all()
        if len(rows) != 2 or {r["name"] for r in rows} != set(PREVIOUS):
            raise RuntimeError("Unexpected number of 2027 field/planting records")

        culture_ids = {
            item["name"]: item["id"] for item in conn.execute(text("""
                SELECT id, name FROM cultures
                WHERE name IN ('Соняшник', 'Пшениця озима')
            """)).mappings().all()
        }
        if set(culture_ids) != {"Соняшник", "Пшениця озима"}:
            raise RuntimeError("Source cultures not found in dictionary")

        before = []
        after = []
        for row in rows:
            old = PREVIOUS[row["name"]]
            original = source_rows[row["name"]]
            new_area = Decimal(original["area"])
            if (row["planting_id"] is None
                    or row["company_name"] != "Митрофанівська ПП"
                    or Decimal(str(row["field_area"])) != old["area"]
                    or Decimal(str(row["planted_area"])) != old["area"]
                    or row["culture_name"] != old["culture"]):
                raise RuntimeError(f"Field {row['name']} is not in the approved test state")

            # Bound record and planting IDs come from verified season-scoped query.
            conn.execute(text("""
                UPDATE field_seasons SET area=:area
                WHERE id=:id AND season_id=:season
            """), {"area": str(new_area), "id": row["record_id"], "season": season["id"]})
            conn.execute(text("""
                UPDATE field_plantings SET area=:area, culture_id=:crop
                WHERE id=:id AND field_season_id=:record
            """), {
                "area": str(new_area),
                "crop": culture_ids[original["culture"]],
                "id": row["planting_id"],
                "record": row["record_id"],
            })
            before.append({
                "field": row["name"], "area": str(old["area"]),
                "culture": old["culture"],
            })
            after.append({
                "field": row["name"], "area": str(new_area),
                "culture": original["culture"],
            })

        result = conn.execute(text("""
            SELECT COUNT(*) AS records, SUM(fp.area) AS planted
            FROM field_seasons fs
            JOIN field_plantings fp ON fp.field_season_id=fs.id
            WHERE fs.season_id=:season
        """), {"season": season["id"]}).mappings().one()
        if (result["records"] != 547
                or Decimal(str(result["planted"])) != EXPECTED_TOTAL_AFTER):
            raise RuntimeError("Correction failed 2027 final total control")

        conn.execute(text("""
            INSERT INTO agroerp_structure_corrections
                (operation_key, season_year, before_details, after_details)
            VALUES (:key, 2027, :before, :after)
        """), {
            "key": OPERATION,
            "before": json.dumps(before, ensure_ascii=False),
            "after": json.dumps(after, ensure_ascii=False),
        })
        return {
            "corrected_fields": len(after),
            "total_2027_ha": str(EXPECTED_TOTAL_AFTER),
            "updated": after,
        }


def correct_if_requested():
    if os.getenv(ENV_NAME) != ENV_TOKEN:
        return
    result = correct_two_fields()
    print("AgroERP two 2027 demo fields correction:", result, flush=True)
