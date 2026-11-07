"""One-time historical crop-structure importer for the isolated test DB.

The private source payload is supplied only through Render environment variables.
No farm-level source data is committed to the public GitHub repository.
"""
import json
import os
from collections import Counter
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from sqlalchemy import text

EXPECTED = {
    2024: (560, Decimal("35195.66")),
    2025: (563, Decimal("34686.88")),
    2026: (550, Decimal("34443.91")),
}
DEMO_FIELDS = {"DEMO 001", "DEMO 002", "DEMO 003"}


def _assert_staging():
    if os.getenv("AGROERP_ENV") != "staging":
        raise RuntimeError("Refusing to import outside staging.")
    raw = os.getenv("RENDER_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if urlparse(raw).path.rstrip("/") != "/agro_erp_test":
        raise RuntimeError("Refusing to import into a database other than agro_erp_test.")


def _load_payload():
    try:
        count = int(os.environ["AGROERP_IMPORT_N"])
    except (ValueError, KeyError) as exc:
        raise RuntimeError("Import chunk count is missing or invalid.") from exc
    if not 1 <= count <= 64:
        raise RuntimeError("Import chunk count outside allowed range.")
    chunks = [os.environ.get(f"AGROERP_IMPORT_{i:03d}", "") for i in range(1, count + 1)]
    if not all(chunks):
        raise RuntimeError("Missing historical data chunks; refusing any writes.")
    data = json.loads("".join(chunks))
    if set(data) != {"orgs", "crops", "rows"}:
        raise RuntimeError("Unexpected historical import payload structure.")
    return data


def _validate(data):
    orgs, crops, rows = data["orgs"], data["crops"], data["rows"]
    if len(orgs) != 16 or len(crops) != 10 or len(rows) != 603:
        raise RuntimeError("Unexpected reference list sizes or field count.")
    if len(set(orgs)) != len(orgs) or len(set(crops)) != len(crops):
        raise RuntimeError("Non-unique reference names.")

    counts = Counter()
    areas = Counter()
    codes = set()
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 8:
            raise RuntimeError("Malformed field row.")
        org_idx, code, *yr_data = row
        if type(org_idx) is not int or not 0 <= org_idx < len(orgs):
            raise RuntimeError("Invalid enterprise index.")
        if not isinstance(code, str) or not code.strip() or code in codes:
            raise RuntimeError("Missing or duplicate field code.")
        codes.add(code)
        parsed_years = {}
        for idx, year in enumerate((2024, 2025, 2026)):
            area, crop_idx = yr_data[2 * idx:2 * idx + 2]
            if area is None and crop_idx is None:
                continue
            if area is None or crop_idx is None:
                raise RuntimeError(f"Incomplete crop-year data for {year}.")
            if type(crop_idx) is not int or not 0 <= crop_idx < len(crops):
                raise RuntimeError("Invalid culture index.")
            try:
                ha = Decimal(str(area))
            except (InvalidOperation, ValueError) as exc:
                raise RuntimeError("Non-numeric area.") from exc
            if not ha.is_finite() or ha <= 0 or ha != ha.quantize(Decimal("0.01")):
                raise RuntimeError("Invalid hectare precision or value.")
            parsed_years[year] = (ha, crops[crop_idx])
            counts[year] += 1
            areas[year] += ha
        if not parsed_years:
            raise RuntimeError("No active years for a field.")
        parsed.append((orgs[org_idx], code, parsed_years))
    for year, (expected_count, expected_area) in EXPECTED.items():
        if (counts[year], areas[year]) != (expected_count, expected_area):
            raise RuntimeError(f"Source checksums differ for {year}: count or hectares.")
    return parsed


def main():
    _assert_staging()
    parsed = _validate(_load_payload())

    # Imports must not create new tables or silently migrate a production database.
    from app import create_app
    from extensions import db
    from modules.reference.clusters.models import Cluster
    from modules.reference.companies.models import Company
    from modules.reference.cultures.models import Culture
    from modules.reference.fields.field_models import Field
    from modules.plans.models import Plan, Treatment
    from modules.purchases.payer_allocation.models import PayerAllocation
    from modules.requests.shipments.models import ShipmentRequest
    from modules.structure.seasons.models import Season, FieldSeason, FieldPlanting

    app = create_app()
    with app.app_context():
        dbname = db.session.execute(text("SELECT current_database()")).scalar_one()
        if dbname != "agro_erp_test":
            raise RuntimeError("Database name mismatch; import refused.")
        current_fields = {r[0] for r in db.session.query(Field.name).all()}
        current_seasons = {r[0] for r in db.session.query(Season.year).all()}
        if len(current_fields) == 603 and current_seasons == set(EXPECTED):
            actual = {
                int(year): (int(cnt), Decimal(area))
                for year, cnt, area in db.session.execute(text(
                    "SELECT s.year, COUNT(fs.id), SUM(fs.area) "
                    "FROM seasons s JOIN field_seasons fs ON fs.season_id=s.id "
                    "GROUP BY s.year"
                ))
            }
            if actual == EXPECTED:
                print("Historical crop structure already imported; skipped.")
                return
            raise RuntimeError("Unexpected prior import: refusing to overwrite.")

        if current_fields != DEMO_FIELDS or current_seasons != {2026, 2027}:
            raise RuntimeError("Staging is not in expected demo-only state; refusing to overwrite.")
        if (db.session.query(Plan).count() or db.session.query(Treatment).count()
                or db.session.query(PayerAllocation).count()
                or db.session.query(ShipmentRequest).count()):
            raise RuntimeError("Dependent operational records exist; refusing to replace demo structure.")
        if db.session.query(Company).count() != 1 or db.session.query(Cluster).count() != 1:
            raise RuntimeError("Unexpected reference records exist in staging.")

        # Single transaction: either all 3 seasons import successfully, or none do.
        db.session.query(FieldPlanting).delete(synchronize_session=False)
        db.session.query(FieldSeason).delete(synchronize_session=False)
        db.session.query(Season).delete(synchronize_session=False)
        db.session.query(Field).delete(synchronize_session=False)
        db.session.query(Company).delete(synchronize_session=False)
        db.session.query(Culture).delete(synchronize_session=False)
        db.session.query(Cluster).delete(synchronize_session=False)

        cluster = Cluster(name="Без кластеризації (історичне джерело)")
        db.session.add(cluster)
        db.session.flush()
        companies = {}
        for name in sorted({name for name, _, _ in parsed}):
            company = Company(name=name, cluster_id=cluster.id)
            db.session.add(company)
            companies[name] = company
        cultures = {}
        for name in sorted({culture for _, _, ys in parsed for _, culture in ys.values()}):
            culture = Culture(name=name)
            db.session.add(culture)
            cultures[name] = culture
        seasons = {year: Season(year=year) for year in EXPECTED}
        db.session.add_all([*companies.values(), *cultures.values(), *seasons.values()])
        db.session.flush()

        for org, code, ys in parsed:
            latest_year = max(ys)
            latest_area, latest_crop = ys[latest_year]
            field = Field(
                name=code, company_id=companies[org].id, cluster_id=cluster.id,
                culture_id=cultures[latest_crop].id, area=float(latest_area), is_active=True,
            )
            db.session.add(field)
            db.session.flush()
            for year, (ha, crop) in ys.items():
                fs = FieldSeason(
                    season_id=seasons[year].id, field_id=field.id, area=ha,
                    company_id=companies[org].id, cluster_id=cluster.id,
                )
                db.session.add(fs)
                db.session.flush()
                db.session.add(FieldPlanting(field_season_id=fs.id, area=ha,
                                             culture_id=cultures[crop].id))
        db.session.commit()
        print("Historical harvest seasons 2024–2026 imported; 603 unique fields.")


if __name__ == "__main__":
    main()
