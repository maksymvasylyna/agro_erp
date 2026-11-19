"""Security and integrity regression checks for the existing planning UI."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "planning-tests-not-for-production-123456789"
os.environ["ADMIN_PASSWORD"] = "planning-admin-only-for-tests-2026"

from sqlalchemy.exc import IntegrityError

from app import create_app
from extensions import db
from modules.plans.models import Plan, Treatment
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from modules.reference.treatment_types.models import TreatmentType


class PlanningHardeningTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                               ADMIN_PASSWORD="planning-admin-only-for-tests-2026")
        self.ctx = self.app.app_context()
        self.ctx.push()
        cluster = Cluster(name="Test cluster")
        company = Company(name="Test company", cluster=cluster)
        culture = Culture(name="Wheat")
        field = Field(name="FIELD-A", area=999.0, cluster=cluster,
                      company=company, culture=culture, is_active=True)
        unit = Unit(name="litre")
        product = Product(name="Product A", unit=unit, is_archived=False)
        type_ = TreatmentType(name="Fungicide")
        db.session.add_all([cluster, company, culture, field, unit, product, type_])
        db.session.flush()
        season = Season.query.filter_by(year=2026).one()
        fs = FieldSeason(season_id=season.id, field_id=field.id,
                         company_id=company.id, cluster_id=cluster.id,
                         area=Decimal("100"))
        db.session.add(fs)
        db.session.flush()
        db.session.add(FieldPlanting(field_season_id=fs.id, culture_id=culture.id,
                                     area=Decimal("100")))
        db.session.commit()
        self.ids = dict(field=field.id, season=season.id, cluster=cluster.id,
                        company=company.id, product=product.id, treatment=type_.id,
                        field_season=fs.id)
        self.client = self.app.test_client()
        self.client.get("/fields/select-season",
                        query_string={"year": 2026, "next": "/plans/"})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def create_plan(self, rate="2.5", product_id=None):
        return self.client.post(f"/new_plans/create/{self.ids['field']}", data={
            "season_id": str(self.ids["season"]),
            "treatments-0-treatment_type_id": str(self.ids["treatment"]),
            "treatments-0-product_id": str(product_id or self.ids["product"]),
            "treatments-0-rate": rate,
        })

    def admin_login(self):
        response = self.client.post("/admin/login", data={
            "password": "planning-admin-only-for-tests-2026"
        })
        self.assertEqual(response.status_code, 302)

    def action(self, path, season_id=None):
        return self.client.post(path, data={
            "season_id": str(season_id or self.ids["season"]),
        })

    def test_approve_requires_admin_post_and_unlocked_season(self):
        self.assertEqual(self.create_plan().status_code, 302)
        plan = Plan.query.one()
        approve = f"/plans/ready/approve_plan/{plan.id}"
        self.assertEqual(self.client.get(approve).status_code, 405)
        self.assertEqual(self.action(approve).status_code, 403)
        self.assertFalse(db.session.get(Plan, plan.id).is_approved)
        self.admin_login()
        self.assertEqual(self.action(approve, season_id=999999).status_code, 409)
        self.assertEqual(self.action(approve).status_code, 302)
        self.assertTrue(db.session.get(Plan, plan.id).is_approved)
        self.assertEqual(self.client.get(f"/plans/ready/{plan.id}/edit").status_code, 409)
        self.assertEqual(self.action(f"/plans/ready/delete/{plan.id}").status_code, 409)
        self.assertEqual(Plan.query.count(), 1)
        unlock = f"/approved_plans/unlock/{plan.id}"
        self.assertEqual(self.client.get(unlock).status_code, 405)
        season = db.session.get(Season, self.ids["season"])
        season.is_closed = True
        db.session.commit()
        self.assertEqual(self.action(unlock).status_code, 409)
        self.assertTrue(db.session.get(Plan, plan.id).is_approved)

    def test_unapprove_requires_admin_post_and_valid_csrf_action(self):
        self.create_plan()
        p = Plan.query.one()
        p.is_approved = True
        db.session.commit()
        endpoint = f"/approved_plans/{p.id}/unapprove"
        self.assertEqual(self.action(endpoint).status_code, 403)
        self.admin_login()
        self.assertEqual(self.action(endpoint).status_code, 302)
        self.assertFalse(db.session.get(Plan, p.id).is_approved)
        self.assertEqual(self.action(endpoint).status_code, 409)

    def test_delete_requires_admin_and_closed_season_blocks(self):
        self.create_plan()
        p = Plan.query.one()
        route = f"/plans/ready/delete/{p.id}"
        self.assertEqual(self.action(route).status_code, 403)
        self.assertEqual(Plan.query.count(), 1)
        self.admin_login()
        s = db.session.get(Season, self.ids["season"])
        s.is_closed = True
        db.session.commit()
        self.assertEqual(self.action(route).status_code, 409)
        self.assertEqual(Plan.query.count(), 1)
        s.is_closed = False
        db.session.commit()
        self.assertEqual(self.action(route).status_code, 302)
        self.assertEqual(Plan.query.count(), 0)

    def test_bulk_approve_only_selected_ready_plans(self):
        self.create_plan()
        plan = Plan.query.one()
        endpoint = "/plans/ready/bulk_approve"
        data = {"season_id": str(self.ids["season"]), "plan_ids": [str(plan.id)]}
        self.assertEqual(self.client.post(endpoint, data=data).status_code, 403)
        self.admin_login()
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season"]),
            "plan_ids": [str(plan.id), "9999"],
        }).status_code, 409)
        self.assertFalse(db.session.get(Plan, plan.id).is_approved)
        self.assertEqual(self.client.post(endpoint, data=data).status_code, 302)
        self.assertTrue(db.session.get(Plan, plan.id).is_approved)

    def test_edit_never_trusts_hidden_quantity_or_current_field_snapshot(self):
        self.create_plan()
        plan = Plan.query.one()
        form = {
            "season_id": str(self.ids["season"]),
            "treatments-0-treatment_type_id": str(self.ids["treatment"]),
            "treatments-0-product_id": str(self.ids["product"]),
            "treatments-0-rate": "1.25",
            "treatments-0-quantity": "999999",
            "treatments-0-unit": "FORGED",
            "treatments-0-manufacturer": "FORGED",
        }
        response = self.client.post(f"/plans/ready/{plan.id}/edit", data=form)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:600])
        line = Treatment.query.filter_by(plan_id=plan.id).one()
        self.assertEqual(line.quantity, 125.0)
        self.assertEqual(line.unit, "litre")
        self.assertNotEqual(line.manufacturer, "FORGED")
        self.assertEqual(self.client.post(f"/plans/ready/{plan.id}/edit", data={
            **form, "treatments-0-rate": "-4",
        }).status_code, 400)
        self.assertEqual(Treatment.query.filter_by(plan_id=plan.id).one().quantity, 125.0)

    def test_real_csrf_required_for_sensitive_action(self):
        import re
        self.create_plan()
        plan = Plan.query.one()
        self.admin_login()
        # Verify against actual Flask-WTF token validation, not the relaxed
        # default used by the rest of the isolated integration tests.
        self.app.config["WTF_CSRF_ENABLED"] = True
        page = self.client.get("/plans/ready/")
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="csrf_token" value="([^"]+)"',
                          page.get_data(as_text=True))
        self.assertIsNotNone(match)
        endpoint = f"/plans/ready/approve_plan/{plan.id}"
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season"])
        }).status_code, 400)
        self.assertFalse(db.session.get(Plan, plan.id).is_approved)
        self.assertEqual(self.client.post(endpoint, data={
            "season_id": str(self.ids["season"]),
            "csrf_token": match.group(1),
        }).status_code, 302)
        self.assertTrue(db.session.get(Plan, plan.id).is_approved)

    def test_one_crop_per_field_and_uniqueness(self):
        # A second planting in the same field violates business selection logic.
        p = FieldPlanting.query.filter_by(field_season_id=self.ids["field_season"]).one()
        p.area = Decimal("60")
        db.session.add(FieldPlanting(field_season_id=p.field_season_id,
                                     culture_id=p.culture_id, area=Decimal("40")))
        db.session.commit()
        field_url = f"/new_plans/select_field/{self.ids['cluster']}/{self.ids['company']}"
        self.assertNotIn("FIELD-A", self.client.get(field_url).get_data(as_text=True))
        self.assertEqual(self.create_plan().status_code, 409)
        db.session.delete(FieldPlanting.query.filter_by(
            field_season_id=self.ids["field_season"]).filter(FieldPlanting.id != p.id).one())
        p.area = Decimal("100")
        db.session.commit()
        self.assertEqual(self.create_plan().status_code, 302)
        db.session.add(Plan(field_id=self.ids["field"], season_id=self.ids["season"]))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        self.assertEqual(Plan.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
