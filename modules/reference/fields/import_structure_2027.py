"""Guarded, one-time import of the 2027 sowing structure.

Source is the 2027 W:X columns of the existing main field-history sheet.
No prior seasons are changed. Previously entered 2027 records are left
unchanged and any source differences are logged as explicit conflicts.
"""
import json
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from extensions import db

ENV_FLAG = "AGROERP_IMPORT_STRUCTURE_2027_ONCE"
ENV_VALUE = "IMPORT_547_FIELDS_FROM_MAIN_HISTORY_2027"
OPERATION = "history_2027_547_fields_2026_11_17"
ALLOWED_EXISTING = {"МТ0 002", "МТ1 002"}
CULTURE_ALIASES = {"Горох озимий": "Горох зимуючий"}


def _source():
    path = Path(__file__).parent / "import_data" / "structure_2027.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    if data["season"] != 2027 or data["row_count"] != 547 or len(rows) != 547:
        raise ValueError("Unexpected 2027 source row count/year")
    if data["source_total_area"] != "34238.87":
        raise ValueError("Unexpected source control total")
    total = Decimal("0.00")
    seen = set()
    for item in rows:
        if not all((item.get("field"), item.get("company"), item.get("culture"))):
            raise ValueError(f"Incomplete source row {item.get('source_row')}")
        area = Decimal(item["area"])
        if area <= 0 or area.as_tuple().exponent < -2:
            raise ValueError(f"Invalid precision/area at {item['source_row']}")
        total += area
        if item["field"] in seen:
            raise ValueError(f"Repeated field name {item['field']}")
        seen.add(item["field"])
    if total != Decimal(data["source_total_area"]):
        raise ValueError("2027 source total failed validation")
    return rows


def run_import():
    """Single atomic import; safe to retry and safe across web workers."""
    rows = _source()
    with db.engine.begin() as conn:
        if db.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(2027, 547)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agroerp_structure_imports (
              operation_key text PRIMARY KEY,
              season_year integer NOT NULL,
              source_rows integer NOT NULL,
              new_fields integer NOT NULL,
              new_field_seasons integer NOT NULL,
              new_plantings integer NOT NULL,
              matched_existing integer NOT NULL,
              conflicting_existing integer NOT NULL,
              conflict_details text NOT NULL,
              created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        if conn.execute(text(
            "SELECT 1 FROM agroerp_structure_imports WHERE operation_key=:key"
        ), {"key": OPERATION}).first():
            return {"already_imported": True}

        season = conn.execute(text(
            "SELECT id, is_closed FROM seasons WHERE year=2027"
        )).mappings().first()
        if season is None or season["is_closed"]:
            raise RuntimeError("2027 season missing or closed; no data imported")

        existing_rows = conn.execute(text("""
            SELECT fs.id, f.name AS field_name, fs.field_id, fs.company_id,
                   fs.cluster_id, fs.area
            FROM field_seasons fs
            JOIN fields f ON f.id = fs.field_id
            WHERE fs.season_id = :id
        """), {"id": season["id"]}).mappings().all()
        unexpected = {r["field_name"] for r in existing_rows} - ALLOWED_EXISTING
        if unexpected:
            raise RuntimeError(
                "2027 has records not in the verified two-row pre-import state: "
                + ", ".join(sorted(unexpected)[:10])
            )
        if len(existing_rows) > 2:
            raise RuntimeError("2027 pre-import record count changed")

        companies = {
            r["name"]: r for r in conn.execute(text(
                "SELECT id, name, cluster_id FROM companies"
            )).mappings().all()
        }
        cultures = {
            r["name"]: r["id"] for r in conn.execute(text(
                "SELECT id, name FROM cultures"
            )).mappings().all()
        }
        if any(r["company"] not in companies for r in rows):
            raise RuntimeError("Unmapped 2027 company: " + ", ".join(sorted({
                r["company"] for r in rows if r["company"] not in companies
            })))
        if any(CULTURE_ALIASES.get(r["culture"], r["culture"]) not in cultures
               for r in rows):
            raise RuntimeError("Unmapped 2027 crop")
        if any(companies[r["company"]]["cluster_id"] is None for r in rows):
            raise RuntimeError("Company missing cluster")

        fields = {}
        for item in conn.execute(text(
            "SELECT id, name, company_id FROM fields"
        )).mappings().all():
            if item["name"] in fields:
                raise RuntimeError("Ambiguous duplicate dictionary field name: " + item["name"])
            fields[item["name"]] = item

        existing = {r["field_name"]: r for r in existing_rows}
        previous_plantings = {}
        if existing_rows:
            for item in conn.execute(text("""
                SELECT fs.id AS record_id, p.culture_id, p.area
                FROM field_seasons fs
                LEFT JOIN field_plantings p ON p.field_season_id=fs.id
                WHERE fs.season_id=:id
            """), {"id": season["id"]}).mappings().all():
                previous_plantings.setdefault(item["record_id"], []).append(item)

        new_fields = 0
        new_records = 0
        new_plantings = 0
        matched = 0
        conflicts = []
        for item in rows:
            company = companies[item["company"]]
            crop_name = CULTURE_ALIASES.get(item["culture"], item["culture"])
            crop_id = cultures[crop_name]
            area = Decimal(item["area"])
            field = fields.get(item["field"])

            if field is not None and field["company_id"] != company["id"]:
                raise RuntimeError("Field/company conflict: " + item["field"])

            previous = existing.get(item["field"])
            if previous:
                plantings = previous_plantings.get(previous["id"], [])
                same = (
                    previous["company_id"] == company["id"]
                    and previous["cluster_id"] == company["cluster_id"]
                    and Decimal(previous["area"]) == area
                    and len(plantings) == 1
                    and plantings[0]["culture_id"] == crop_id
                    and Decimal(plantings[0]["area"]) == area
                )
                if same:
                    matched += 1
                else:
                    conflicts.append({
                        "field": item["field"],
                        "source_row": item["source_row"],
                        "source_area": str(area),
                        "source_culture": item["culture"],
                        "existing_area": str(previous["area"]),
                        "existing_culture_ids": [
                            p["culture_id"] for p in plantings
                        ],
                        "existing_planting_areas": [
                            str(p["area"]) for p in plantings
                        ],
                    })
                # Intentional: never overwrite manually entered season rows.
                continue

            if field is None:
                field_id = conn.execute(text("""
                    INSERT INTO fields
                      (name, is_active, company_id, cluster_id, culture_id, area)
                    VALUES (:name, TRUE, :company, :cluster, :crop, :area)
                    RETURNING id
                """), {
                    "name": item["field"], "company": company["id"],
                    "cluster": company["cluster_id"], "crop": crop_id,
                    "area": float(area),
                }).scalar_one()
                fields[item["field"]] = {
                    "id": field_id, "name": item["field"],
                    "company_id": company["id"],
                }
                new_fields += 1
            else:
                field_id = field["id"]

            record_id = conn.execute(text("""
                INSERT INTO field_seasons
                  (season_id, field_id, company_id, cluster_id, area)
                VALUES (:season, :field, :company, :cluster, :area)
                RETURNING id
            """), {
                "season": season["id"], "field": field_id,
                "company": company["id"], "cluster": company["cluster_id"],
                "area": area,
            }).scalar_one()
            conn.execute(text("""
                INSERT INTO field_plantings
                  (field_season_id, culture_id, area, note)
                VALUES (:record, :crop, :area, NULL)
            """), {
                "record": record_id, "crop": crop_id, "area": area,
            })
            new_records += 1
            new_plantings += 1

        conn.execute(text("""
            INSERT INTO agroerp_structure_imports (
              operation_key, season_year, source_rows, new_fields,
              new_field_seasons, new_plantings, matched_existing,
              conflicting_existing, conflict_details)
            VALUES (
              :key, 2027, :source, :fields, :records, :plantings,
              :matched, :conflicts, :details
            )
        """), {
            "key": OPERATION, "source": len(rows), "fields": new_fields,
            "records": new_records, "plantings": new_plantings,
            "matched": matched, "conflicts": len(conflicts),
            "details": json.dumps(conflicts, ensure_ascii=False),
        })
        return {
            "new_fields": new_fields,
            "new_records": new_records,
            "new_plantings": new_plantings,
            "matched": matched,
            "conflicts": conflicts,
        }


def import_if_requested():
    if os.getenv(ENV_FLAG) != ENV_VALUE:
        return
    result = run_import()
    print("AgroERP 2027 structure import:", {
        k: (len(v) if isinstance(v, list) else v) for k, v in result.items()
    }, flush=True)
