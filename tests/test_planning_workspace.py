"""Integration checks for additive crop-level planning workspace."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "local-test-key-not-for-production-1234567890"

from app import create_app
from extensions import db
from modules.plans.workspace.models import TechnologyPlan, TechnologyOperation
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType
from modules.reference.units.models import Unit


class PlanningWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        cluster = Cluster(name="Північ")
        company = Company(name="Підприємство А", cluster=cluster)
        southern = Cluster(name="Південь")
        company_south = Company(name="Підприємство Б", cluster=southern)
        wheat = Culture(name="Пшениця")
        rape = Culture(name="Ріпак")
        field = Field(name="ПОЛЕ 125-А", area=999.0, cluster=cluster,
                      company=company, culture=wheat, is_active=True)
        rape_field = Field(name="ПОЛЕ 125-Б", area=40.0, cluster=cluster,
                           company=company, culture=rape, is_active=True)
        south_field = Field(name="ПОЛЕ 999", area=10.0, cluster=southern,
                            company=company_south, culture=rape, is_active=True)
        unit = Unit(name="л")
        product = Product(name="Продукт А", unit=unit)
        second = Product(name="Продукт Б", unit=unit)
        archived = Product(name="Неактивний продукт", unit=unit, is_archived=True)
        treatment_type = TreatmentType(name="Фунгіцид Т1")
        db.session.add_all([cluster, company, southern, company_south,
                            wheat, rape, field, rape_field, south_field, unit,
                            product, second, archived, treatment_type])
        db.session.flush()
        s26 = Season.query.filter_by(year=2026).one()
        s27 = Season.query.filter_by(year=2027).one()
        fs26 = FieldSeason(season_id=s26.id, field_id=field.id, cluster_id=cluster.id,
                           company_id=company.id, area=Decimal("60.00"))
        rape_fs = FieldSeason(season_id=s26.id, field_id=rape_field.id, cluster_id=cluster.id,
                              company_id=company.id, area=Decimal("40.00"))
        fs27 = FieldSeason(season_id=s27.id, field_id=field.id, cluster_id=cluster.id,
                           company_id=company.id, area=Decimal("90.00"))
        south_fs = FieldSeason(season_id=s26.id, field_id=south_field.id, cluster_id=southern.id,
                               company_id=company_south.id, area=Decimal("10.00"))
        db.session.add_all([fs26, rape_fs, fs27, south_fs])
        db.session.flush()
        pw = FieldPlanting(field_season_id=fs26.id, culture_id=wheat.id, area=Decimal("60"))
        pr = FieldPlanting(field_season_id=rape_fs.id, culture_id=rape.id, area=Decimal("40"))
        later = FieldPlanting(field_season_id=fs27.id, culture_id=rape.id, area=Decimal("90"))
        south_planting = FieldPlanting(field_season_id=south_fs.id, culture_id=rape.id,
                                       area=Decimal("10"))
        db.session.add_all([pw, pr, later, south_planting])
        db.session.commit()
        self.ids = dict(wheat=pw.id, rape=pr.id, later=later.id, south=south_planting.id,
                        field=field.id, rape_field=rape_field.id, south_field=south_field.id,
                        north_cluster=cluster.id, south_cluster=southern.id,
                        company=company.id, company_south=company_south.id,
                        product=product.id, second=second.id, archived=archived.id,
                        type=treatment_type.id, season26=s26.id, season27=s27.id)
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def select_year(self, year):
        response = self.client.get("/fields/select-season", query_string={
            "year": year, "next": "/plans/workspace/"})
        self.assertEqual(response.status_code, 302)

    def create_plan(self, planting_id, basis="60", product_id=None, season_id=None):
        return self.client.post(f"/plans/workspace/planting/{planting_id}", data={
            "season_id": str(season_id or self.ids["season26"]),
            "operation_count": "1",
            "operations-0-type": str(self.ids["type"]),
            "operations-0-label": "Т1",
            "operations-0-bbch": "31-32",
            "operations-0-basis_unit": "ha",
            "operations-0-basis_quantity": basis,
            "operations-0-product_count": "2",
            "operations-0-products-0-id": str(product_id or self.ids["product"]),
            "operations-0-products-0-rate": "0.5",
            "operations-0-products-1-id": str(self.ids["second"]),
            "operations-0-products-1-rate": "0.3",
        })

    def test_page_rendering_and_editor_for_each_crop(self):
        """Smoke test both pages that users open in a real browser."""
        self.select_year(2026)
        landing = self.client.get("/plans/workspace/")
        self.assertEqual(landing.status_code, 200, landing.get_data(as_text=True)[:900])
        self.assertNotIn("ПОЛЕ 125", landing.get_data(as_text=True))
        for planting_id in (self.ids["wheat"], self.ids["rape"]):
            response = self.client.get(f"/plans/workspace/planting/{planting_id}")
            self.assertEqual(response.status_code, 200,
                             response.get_data(as_text=True)[:1000])
            page = response.get_data(as_text=True)
            self.assertIn("technology-form", page)
            self.assertIn("operations-container", page)
        self.assertEqual(self.create_plan(self.ids["wheat"]).status_code, 302)
        self.assertEqual(self.client.get(
            f"/plans/workspace/planting/{self.ids['wheat']}").status_code, 200)
        self.assertIn("ПОЛЕ 125-А", self.client.get(
            "/plans/workspace/").get_data(as_text=True))

    def test_split_fields_have_independent_plans(self):
        self.select_year(2026)
        a = self.create_plan(self.ids["wheat"])
        b = self.create_plan(self.ids["rape"], basis="40")
        self.assertEqual(a.status_code, 302)
        self.assertEqual(b.status_code, 302)
        plans = TechnologyPlan.query.order_by(TechnologyPlan.planting_id).all()
        self.assertEqual(len(plans), 2)
        self.assertNotEqual(plans[0].planting_id, plans[1].planting_id)
        self.assertEqual({str(p.quantity) for x in plans for o in x.operations
                          for p in o.products}, {"30.000", "18.000", "20.000", "12.000"})
        page = self.client.get("/plans/workspace/").get_data(as_text=True)
        self.assertIn("Пшениця", page)
        self.assertIn("Ріпак", page)
        self.assertIn("ПОЛЕ 125-А", page)
        self.assertIn("ПОЛЕ 125-Б", page)
        self.assertIn("60", page)
        self.assertNotIn("999.0", page)

    def test_creation_wizard_cascade_and_excludes_planned_fields(self):
        self.select_year(2026)
        entry = self.client.get("/new_plans/")
        self.assertEqual(entry.status_code, 200)
        self.assertIn("/plans/workspace/create/cluster", entry.get_data(as_text=True))
        first = self.client.get("/plans/workspace/create/cluster")
        self.assertEqual(first.status_code, 200)
        self.assertIn("Північ", first.get_data(as_text=True))
        self.assertIn("Південь", first.get_data(as_text=True))
        north_url = f"/plans/workspace/create/cluster/{self.ids['north_cluster']}/company"
        company_page = self.client.get(north_url)
        self.assertEqual(company_page.status_code, 200)
        self.assertIn("Підприємство А", company_page.get_data(as_text=True))
        self.assertNotIn("Підприємство Б", company_page.get_data(as_text=True))
        fields_url = (f"/plans/workspace/create/cluster/{self.ids['north_cluster']}"
                      f"/company/{self.ids['company']}/field")
        fields = self.client.get(fields_url).get_data(as_text=True)
        self.assertIn("ПОЛЕ 125-А", fields)
        self.assertIn("ПОЛЕ 125-Б", fields)
        self.assertNotIn("ПОЛЕ 999", fields)
        self.create_plan(self.ids["wheat"])
        fields = self.client.get(fields_url).get_data(as_text=True)
        self.assertNotIn("ПОЛЕ 125-А", fields)
        self.assertIn("ПОЛЕ 125-Б", fields)
        self.create_plan(self.ids["rape"], basis="40")
        fields = self.client.get(fields_url).get_data(as_text=True)
        self.assertNotIn("ПОЛЕ 125-А", fields)
        self.assertNotIn("ПОЛЕ 125-Б", fields)
        self.assertNotIn("Підприємство А", self.client.get(north_url).get_data(as_text=True))
        self.assertNotIn("Північ", self.client.get("/plans/workspace/create/cluster").get_data(as_text=True))
        self.assertIn("Південь", self.client.get("/plans/workspace/create/cluster").get_data(as_text=True))

    def test_legacy_plan_excludes_field_and_blocks_direct_creation(self):
        from modules.plans.models import Plan
        self.select_year(2026)
        db.session.add(Plan(field_id=self.ids["field"], season_id=self.ids["season26"]))
        db.session.commit()
        url = (f"/plans/workspace/create/cluster/{self.ids['north_cluster']}"
               f"/company/{self.ids['company']}/field")
        page = self.client.get(url).get_data(as_text=True)
        self.assertNotIn("ПОЛЕ 125-А", page)
        self.assertIn("ПОЛЕ 125-Б", page)
        self.assertEqual(self.client.get(
            f"/plans/workspace/planting/{self.ids['wheat']}").status_code, 409)
        self.assertEqual(self.create_plan(self.ids["wheat"]).status_code, 409)
        self.assertEqual(TechnologyPlan.query.count(), 0)

    def test_field_with_multiple_crops_must_be_split_before_creation(self):
        self.select_year(2026)
        original = db.session.get(FieldPlanting, self.ids["wheat"])
        db.session.add(FieldPlanting(field_season_id=original.field_season_id,
                                     culture_id=original.culture_id, area=Decimal("1")))
        db.session.commit()
        url = (f"/plans/workspace/create/cluster/{self.ids['north_cluster']}"
               f"/company/{self.ids['company']}/field")
        self.assertNotIn("ПОЛЕ 125-А", self.client.get(url).get_data(as_text=True))
        self.assertEqual(self.create_plan(self.ids["wheat"]).status_code, 409)

    def test_season_isolation_and_reject_stale_form(self):
        self.select_year(2026)
        self.assertEqual(self.create_plan(self.ids["wheat"]).status_code, 302)
        self.select_year(2027)
        self.assertEqual(self.client.get(f"/plans/workspace/planting/{self.ids['wheat']}").status_code, 404)
        self.assertNotIn("Пшениця", self.client.get("/plans/workspace/").get_data(as_text=True))
        self.assertEqual(self.create_plan(self.ids["later"], basis="90",
                         season_id=self.ids["season26"]).status_code, 409)
        self.assertEqual(TechnologyPlan.query.count(), 1)
        self.assertEqual(self.create_plan(self.ids["later"], basis="90",
                         season_id=self.ids["season27"]).status_code, 302)
        self.assertEqual(TechnologyPlan.query.count(), 2)

    def test_status_permissions_and_closed_year(self):
        self.select_year(2026)
        self.create_plan(self.ids["wheat"])
        p = TechnologyPlan.query.one()
        self.assertEqual(p.status, "draft")
        endpoint = f"/plans/workspace/{p.id}/status"
        self.assertEqual(self.client.get(endpoint).status_code, 405)
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season26"]), "action": "ready"}).status_code, 302)
        self.assertEqual(db.session.get(TechnologyPlan, p.id).status, "ready")
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season26"]), "action": "approve"}).status_code, 403)
        s26 = db.session.get(Season, self.ids["season26"])
        s26.is_closed = True
        db.session.commit()
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season26"]), "action": "revise"}).status_code, 409)

    def test_invalid_and_archived_inputs_never_create_plan(self):
        self.select_year(2026)
        self.assertEqual(self.create_plan(self.ids["wheat"], basis="600").status_code, 200)
        self.assertEqual(TechnologyPlan.query.count(), 0)
        self.assertEqual(self.create_plan(self.ids["wheat"], product_id=self.ids["archived"]).status_code, 200)
        self.assertEqual(TechnologyPlan.query.count(), 0)
        self.assertEqual(self.create_plan(self.ids["wheat"], basis="60").status_code, 302)
        self.assertEqual(self.create_plan(self.ids["wheat"], basis="70").status_code, 200)
        plan = TechnologyPlan.query.one()
        self.assertEqual(plan.operations[0].basis_quantity, Decimal("60.000"))


if __name__ == "__main__":
    unittest.main()
