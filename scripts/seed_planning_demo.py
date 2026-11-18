"""Populate *only* an isolated SQLite demo service with artificial agronomy data.

Use with a dedicated preview service without RENDER_DATABASE_URL / DATABASE_URL.
Never run against production PostgreSQL.
"""
from decimal import Decimal
import os
import sys

# Direct script execution starts with scripts/ on sys.path, not repository root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config import Config
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.units.models import Unit


def seed():
    # Explicit guard: avoid seeding real business records by mistake.
    if db.engine.dialect.name != "sqlite":
        raise RuntimeError("Demo seeding is allowed only on isolated SQLite.")
    existing = Cluster.query.filter_by(name="DEMO — кластер").first()
    if existing:
        # Upgrade only the isolated demo fixtures from the older sample where
        # DEMO-001 had two crops. Preserve existing TechnologyPlan/planting IDs.
        first = Field.query.filter_by(name="DEMO-001", cluster_id=existing.id).first()
        if first:
            original = FieldSeason.query.filter_by(field_id=first.id).first()
            if original and len(original.plantings) == 2:
                rapeseed = next((p for p in original.plantings
                                if p.culture.name.startswith("Ріпак")), None)
                if rapeseed:
                    split = Field.query.filter_by(name="DEMO-003",
                                                   cluster_id=existing.id).first()
                    if not split:
                        split = Field(name="DEMO-003", cluster_id=existing.id,
                                      company_id=original.company_id,
                                      culture_id=rapeseed.culture_id,
                                      area=float(rapeseed.area), is_active=True)
                        db.session.add(split)
                        db.session.flush()
                    new_fs = FieldSeason(season_id=original.season_id,
                                         field_id=split.id,
                                         cluster_id=original.cluster_id,
                                         company_id=original.company_id,
                                         area=rapeseed.area)
                    db.session.add(new_fs)
                    db.session.flush()
                    rapeseed.field_season_id = new_fs.id
                    original.area = original.area - new_fs.area
                    first.area = float(original.area)
                    db.session.commit()
        return

    season = Season.query.filter_by(year=2027).one()
    cluster = Cluster(name="DEMO — кластер")
    company = Company(name="DEMO — господарство", cluster=cluster)
    wheat = Culture(name="Пшениця озима — демо")
    rape = Culture(name="Ріпак озимий — демо")
    sunflower = Culture(name="Соняшник — демо")
    field1 = Field(name="DEMO-001", cluster=cluster, company=company,
                   culture=wheat, area=80.0, is_active=True)
    field2 = Field(name="DEMO-002", cluster=cluster, company=company,
                   culture=sunflower, area=150.0, is_active=True)
    field3 = Field(name="DEMO-003", cluster=cluster, company=company,
                   culture=rape, area=40.0, is_active=True)
    liter = Unit(name="л")
    kilo = Unit(name="кг")
    products = [
        Product(name="DEMO Fungicide A", unit=liter),
        Product(name="DEMO Fungicide B", unit=liter),
        Product(name="DEMO Seed Treatment", unit=kilo),
    ]
    types = [TreatmentType(name="Демо — фунгіцид Т1"),
             TreatmentType(name="Демо — протруювання")]
    db.session.add_all([cluster, company, wheat, rape, sunflower, field1,
                        field2, field3, liter, kilo] + products + types)
    db.session.flush()
    fs1 = FieldSeason(season_id=season.id, field_id=field1.id, company_id=company.id,
                      cluster_id=cluster.id, area=Decimal("80"))
    fs2 = FieldSeason(season_id=season.id, field_id=field2.id, company_id=company.id,
                      cluster_id=cluster.id, area=Decimal("150"))
    fs3 = FieldSeason(season_id=season.id, field_id=field3.id, company_id=company.id,
                      cluster_id=cluster.id, area=Decimal("40"))
    db.session.add_all([fs1, fs2, fs3])
    db.session.flush()
    db.session.add_all([
        FieldPlanting(field_season_id=fs1.id, culture_id=wheat.id, area=Decimal("80")),
        FieldPlanting(field_season_id=fs2.id, culture_id=sunflower.id, area=Decimal("150")),
        FieldPlanting(field_season_id=fs3.id, culture_id=rape.id, area=Decimal("40")),
    ])
    db.session.commit()
    print("Seeded isolated planning demo: 3 fields, 3 crop allocations, 3 artificial products.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
