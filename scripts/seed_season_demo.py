"""Seed a few synthetic records ONLY in the isolated staging database.

This script is idempotent. It refuses to run unless the target database is
explicitly the demo database, and never imports real data.
"""
import os
import sys
from pathlib import Path

# When launched as python scripts/seed_season_demo.py, add repo root for app import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal
from urllib.parse import urlparse


def main():
    db_url = os.getenv("DATABASE_URL", "")
    if (
        os.getenv("AGROERP_ENV") != "staging"
        or os.getenv("ALLOW_SEED_DEMO") != "yes"
        or urlparse(db_url).path.rstrip("/") != "/agro_erp_test"
    ):
        raise SystemExit("Demo seed refused: requires staging environment and agro_erp_test database.")

    from app import create_app
    from extensions import db
    from modules.reference.clusters.models import Cluster
    from modules.reference.companies.models import Company
    from modules.reference.cultures.models import Culture
    from modules.reference.fields.field_models import Field
    from modules.structure.seasons.models import Season, FieldSeason, FieldPlanting

    app = create_app()
    with app.app_context():
        if db.session.query(Season.id).first() or db.session.query(Field.id).first():
            print("Demo seed skipped: database already contains fields or seasons.")
            return

        cluster = Cluster(name="Демо-кластер")
        db.session.add(cluster)
        db.session.flush()
        company = Company(name="Тестове господарство", cluster_id=cluster.id)
        wheat = Culture(name="Пшениця озима")
        sunflower = Culture(name="Соняшник")
        corn = Culture(name="Кукурудза")
        db.session.add_all([company, wheat, sunflower, corn])
        db.session.flush()

        fields = []
        for name, area, initial_crop in [
            ("DEMO 001", 100.0, wheat),
            ("DEMO 002", 75.0, sunflower),
            ("DEMO 003", 60.0, corn),
        ]:
            field = Field(name=name, area=area, is_active=True,
                          cluster_id=cluster.id, company_id=company.id,
                          culture_id=initial_crop.id)
            fields.append(field)
        db.session.add_all(fields)
        db.session.flush()

        for year, allocations in [
            (2026, [[(wheat, 100)], [(sunflower, 75)], [(corn, 60)]]),
            (2027, [[(sunflower, 60), (wheat, 40)], [(wheat, 75)], [(corn, 60)]]),
        ]:
            season = Season(year=year)
            db.session.add(season)
            db.session.flush()
            for field, crops in zip(fields, allocations):
                field_season = FieldSeason(
                    season_id=season.id, field_id=field.id, company_id=company.id,
                    cluster_id=cluster.id, area=Decimal(str(field.area)),
                )
                db.session.add(field_season)
                db.session.flush()
                for crop, area in crops:
                    db.session.add(FieldPlanting(
                        field_season_id=field_season.id, culture_id=crop.id,
                        area=Decimal(area),
                        note="Синтетичні дані для перевірки"
                    ))
        db.session.commit()
        print("Seeded synthetic season demo: 2026 and 2027, three fields.")


if __name__ == "__main__":
    main()
