"""Fill only the standalone legacy-planning preview with invented data.

The production AgroERP PostgreSQL database must never be touched.
This file intentionally refuses every database except the dedicated /tmp
SQLite pathname of the hardening preview web service.
"""
from decimal import Decimal
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldPlanting, FieldSeason, Season
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.units.models import Unit
from modules.plans.models import Plan, Treatment

DB_NAME = "/tmp/agro_erp_plans_hardening_2026.sqlite"


def seed():
    if os.getenv("AGROERP_TEST_INSTANCE") != "1":
        raise RuntimeError("Demo seeding requires AGROERP_TEST_INSTANCE=1.")
    if db.engine.dialect.name != "sqlite" or db.engine.url.database != DB_NAME:
        raise RuntimeError("Refusing to seed anything except the isolated demo SQLite database.")
    if os.environ.get("RENDER_DATABASE_URL"):
        raise RuntimeError("Refusing to seed when RENDER_DATABASE_URL exists.")
    if Cluster.query.filter_by(name="DEMO Північний кластер").first():
        print("Old-planning demo is already seeded; keeping existing demo plans.")
        return

    season = Season.query.filter_by(year=2027).one()
    north = Cluster(name="DEMO Північний кластер")
    south = Cluster(name="DEMO Південний кластер")
    company_n = Company(name="DEMO Господарство Північ", cluster=north)
    company_s = Company(name="DEMO Господарство Південь", cluster=south)
    wheat = Culture(name="Пшениця озима — демо")
    rape = Culture(name="Ріпак озимий — демо")
    sunflower = Culture(name="Соняшник — демо")
    unit_l = Unit(name="л")
    unit_kg = Unit(name="кг")
    products = [
        Product(name="DEMO Fungicide A", unit=unit_l),
        Product(name="DEMO Herbicide B", unit=unit_l),
        Product(name="DEMO Insecticide C", unit=unit_kg),
    ]
    operations = [
        TreatmentType(name="DEMO Фунгіцидна обробка"),
        TreatmentType(name="DEMO Гербіцидна обробка"),
        TreatmentType(name="DEMO Інсектицидна обробка"),
    ]
    db.session.add_all([north, south, company_n, company_s, wheat, rape,
                        sunflower, unit_l, unit_kg] + products + operations)
    db.session.flush()

    # One independent field = one independent crop, exactly as agreed.
    cases = [
        ("DEMO-101", north, company_n, wheat, "100.00", "available"),
        ("DEMO-102", north, company_n, rape, "80.00", "available"),
        ("DEMO-103", north, company_n, sunflower, "70.00", "ready"),
        ("DEMO-201", south, company_s, wheat, "110.00", "approved"),
        ("DEMO-202", south, company_s, sunflower, "90.00", "available"),
    ]
    for name, cluster, company, crop, area, state in cases:
        hectares = Decimal(area)
        field = Field(name=name, cluster=cluster, company=company, culture=crop,
                      area=float(hectares), is_active=True)
        db.session.add(field)
        db.session.flush()
        field_season = FieldSeason(season_id=season.id, field_id=field.id,
                                   company_id=company.id, cluster_id=cluster.id,
                                   area=hectares)
        db.session.add(field_season)
        db.session.flush()
        db.session.add(FieldPlanting(field_season_id=field_season.id,
                                     culture_id=crop.id, area=hectares))
        if state != "available":
            plan = Plan(field_id=field.id, season_id=season.id,
                        status="готовий", is_approved=(state == "approved"))
            db.session.add(plan)
            db.session.flush()
            db.session.add(Treatment(
                plan_id=plan.id, treatment_type_id=operations[0].id,
                product_id=products[0].id, rate=1.0,
                quantity=float(hectares), unit=unit_l.name, manufacturer="",
            ))
    db.session.commit()
    print("Seeded separate legacy-planning demo: season 2027, five one-crop fields, "
          "three unplanned, one ready, one approved.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
