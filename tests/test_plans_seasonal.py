"""Disposable SQLite integration tests for Planning season isolation."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ.pop("AGROERP_CLEAR_LEGACY_PLANS_ONCE", None)
os.environ["SECRET_KEY"] = "integration-tests-only-not-production-secret"

from app import create_app
from extensions import db
from modules.plans.models import Plan, Treatment
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting
from modules.reference.manufacturers.models import Manufacturer
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.units.models import Unit


class PlanningSeasonsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.session.add(Season(year=2024))
        cluster = Cluster(name="Кластер Тест")
        company = Company(name="Тестове підприємство", cluster=cluster)
        wheat = Culture(name="Пшениця озима")
        sun = Culture(name="Соняшник")
        field = Field(name="ТЕСТ 001", cluster=cluster, company=company,
                      culture=wheat, area=999.0, is_active=True)
        unit = Unit(name="л")
        man = Manufacturer(name="Виробник")
        product = Product(name="Тестовий продукт", unit=unit, manufacturer=man)
        treatment_type = TreatmentType(name="Внесення по вегетації 1")
        db.session.add_all([cluster, company, wheat, sun, field,
                            unit, man, product, treatment_type])
        db.session.flush()
        s26 = Season.query.filter_by(year=2026).one()
        s27 = Season.query.filter_by(year=2027).one()
        fs26 = FieldSeason(field_id=field.id, season_id=s26.id,
                           cluster_id=cluster.id, company_id=company.id,
                           area=Decimal("100.00"))
        fs27 = FieldSeason(field_id=field.id, season_id=s27.id,
                           cluster_id=cluster.id, company_id=company.id,
                           area=Decimal("80.00"))
        db.session.add_all([fs26, fs27])
        db.session.flush()
        db.session.add_all([
            FieldPlanting(field_season_id=fs26.id, culture_id=wheat.id,
                          area=Decimal("100.00")),
            FieldPlanting(field_season_id=fs27.id, culture_id=sun.id,
                          area=Decimal("80.00")),
        ])
        db.session.commit()
        self.ids = dict(
            field=field.id, company=company.id, cluster=cluster.id,
            product=product.id, treatment_type=treatment_type.id,
            season_2026=s26.id, season_2027=s27.id,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def year(self, value):
        response = self.client.get(
            "/fields/select-season", query_string={
                "year": value, "next": "/plans/",
            }
        )
        self.assertEqual(response.status_code, 302)

    def post_plan(self, year):
        self.year(year)
        sid = self.ids["season_" + str(year)]
        return self.client.post(
            f"/new_plans/create/{self.ids['field']}",
            data={
                "season_id": str(sid),
                "treatments-0-treatment_type_id": str(self.ids["treatment_type"]),
                "treatments-0-product_id": str(self.ids["product"]),
                "treatments-0-rate": "2.5",
            },
        )

    def test_home_is_the_only_season_selector(self):
        self.year(2026)
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        html = home.get_data(as_text=True)
        self.assertEqual(html.count('id="global-season-select"'), 1)
        self.assertIn('value="2026" selected', html)
        paths = (
            "/plans/", "/new_plans/", "/plans/ready/",
            "/approved_plans/", "/plans/summary/", "/fields",
            "/fields/seasons", f"/fields/{self.ids['field']}",
            "/structure/fields", "/summary_structure/",
        )
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn('id="global-season-select"',
                             response.get_data(as_text=True), path)
        self.year(2027)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('value="2027" selected', html)
        self.assertIn("сезону 2027", self.client.get("/plans/").get_data(as_text=True))
        self.year(2026)
        self.assertIn('value="2026" selected',
                      self.client.get("/").get_data(as_text=True))

    def test_current_year_only_and_empty_season(self):
        self.year(2026)
        self.assertIn("2026", self.client.get("/plans/").get_data(as_text=True))
        r26 = self.post_plan(2026)
        self.assertEqual(r26.status_code, 302)
        r27 = self.post_plan(2027)
        self.assertEqual(r27.status_code, 302)
        self.assertEqual(Plan.query.count(), 2)
        a = Plan.query.filter_by(season_id=self.ids["season_2026"]).one()
        b = Plan.query.filter_by(season_id=self.ids["season_2027"]).one()
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(a.treatments[0].quantity, 250.0)
        self.assertEqual(b.treatments[0].quantity, 200.0)

        self.year(2026)
        page = self.client.get("/plans/ready/").get_data(as_text=True)
        self.assertIn(f"<td>{a.id}</td>", page)
        self.assertNotIn(f"<td>{b.id}</td>", page)
        self.assertIn("сезон 2026", page)
        self.assertEqual(self.client.get(f"/plans/ready/{b.id}").status_code, 404)

        self.year(2027)
        page = self.client.get("/plans/ready/").get_data(as_text=True)
        self.assertIn(f"<td>{b.id}</td>", page)
        self.assertNotIn(f"<td>{a.id}</td>", page)
        self.assertEqual(self.client.get(f"/plans/ready/{a.id}").status_code, 404)

        self.year(2024)
        page = self.client.get("/plans/ready/").get_data(as_text=True)
        self.assertIn("У сезоні 2024 готових планів немає", page)

    def test_all_summaries_and_pdf_are_season_filtered(self):
        self.post_plan(2026)
        self.post_plan(2027)
        for p in Plan.query.all():
            p.is_approved = True
        db.session.commit()
        self.year(2026)
        self.assertEqual(
            self.client.get("/plans/ready/").status_code, 200
        )
        page = self.client.get("/approved_plans/").get_data(as_text=True)
        self.assertIn("2026", page)
        self.assertEqual(page.count("👁️ Перегляд"), 1)
        summary = self.client.get("/plans/summary/").get_data(as_text=True)
        self.assertIn("250.00", summary)
        self.assertNotIn("200.00", summary)
        wrong = Plan.query.filter_by(season_id=self.ids["season_2027"]).one()
        self.assertEqual(
            self.client.get(f"/approved_plans/{wrong.id}").status_code, 404
        )
        self.assertEqual(self.client.get("/approved_plans/export_pdf").status_code, 200)
        self.assertEqual(self.client.get("/plans/summary/pdf").status_code, 200)

    def test_season_must_match_form_and_field(self):
        self.year(2026)
        form = self.client.get(
            f"/new_plans/create/{self.ids['field']}"
        ).get_data(as_text=True)
        self.assertIn(f'value="{self.ids["season_2026"]}"', form)
        self.assertIn("100.00 га", form)
        self.assertNotIn("999.0 га", form)
        self.year(2027)
        mismatch = self.client.post(
            f"/new_plans/create/{self.ids['field']}",
            data={"season_id": str(self.ids["season_2026"])},
        )
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(Plan.query.count(), 0)
        selected = self.client.get(
            f"/new_plans/select_field/{self.ids['cluster']}/{self.ids['company']}"
        ).get_data(as_text=True)
        self.assertIn("80.00 га", selected)
        self.assertIn("Соняшник", selected)

    def test_bulk_selection_does_not_leak_other_seasons(self):
        self.year(2024)
        page = self.client.get(
            "/new_plans/bulk_template/select_fields"
        ).get_data(as_text=True)
        self.assertNotIn("ТЕСТ 001</td>", page)
        self.year(2027)
        page = self.client.get(
            "/new_plans/bulk_template/select_fields"
        ).get_data(as_text=True)
        self.assertIn("ТЕСТ 001", page)
        self.assertIn("80.00", page)
        self.assertNotIn("999.0", page)
        bad = self.client.post(
            "/new_plans/bulk_template/create",
            data={
                "field_ids": str(self.ids["field"]),
                "season_id": str(self.ids["season_2026"]),
            },
        )
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(Plan.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
