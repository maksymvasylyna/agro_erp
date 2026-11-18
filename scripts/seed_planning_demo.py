"""Populate *only* an isolated SQLite demo service with artificial agronomy data.

Use with a dedicated preview service without RENDER_DATABASE_URL / DATABASE_URL.
Never run against production PostgreSQL.
"""
from decimal import Decimal

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
    if Cluster.query.filter_by(name="DEMO — кластер").first():
        return

    season = Season.query.filter_by(year=2027).one()
    cluster = Cluster(name="DEMO — кластер")
    company = Company(name="DEMO — господарство", cluster=cluster)
    wheat = Culture(name="Пшениця озима — демо")
    rape = Culture(name="Ріпак озимий — демо")
    sunflower = Culture(name="Соняшник — демо")
    field1 = Field(name="DEMO-001", cluster=cluster, company=company,
                   culture=wheat, area=120.0, is_active=True)
    field2 = Field(name="DEMO-002", cluster=cluster, company=company,
                   culture=sunflower, area=150.0, is_active=True)
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
                        field2, liter, kilo] + products + types)
    db.session.flush()
    fs1 = FieldSeason(season_id=season.id, field_id=field1.id, company_id=company.id,
                      cluster_id=cluster.id, area=Decimal("120"))
    fs2 = FieldSeason(season_id=season.id, field_id=field2.id, company_id=company.id,
                      cluster_id=cluster.id, area=Decimal("150"))
    db.session.add_all([fs1, fs2])
    db.session.flush()
    db.session.add_all([
        FieldPlanting(field_season_id=fs1.id, culture_id=wheat.id, area=Decimal("80")),
        FieldPlanting(field_season_id=fs1.id, culture_id=rape.id, area=Decimal("40")),
        FieldPlanting(field_season_id=fs2.id, culture_id=sunflower.id, area=Decimal("150")),
    ])
    db.session.commit()
    print("Seeded isolated planning demo: 2 fields, 3 crop allocations, 3 artificial products.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
