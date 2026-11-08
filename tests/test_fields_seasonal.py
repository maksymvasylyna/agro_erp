"""Disposable field-directory integration tests (never use Render PostgreSQL)."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-secret-key-for-seasonal-fields-only-2026"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from modules.reference.clusters.models import Cluster  # noqa: E402
from modules.reference.companies.models import Company  # noqa: E402
from modules.reference.cultures.models import Culture  # noqa: E402
from modules.reference.fields.field_models import Field  # noqa: E402
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting  # noqa: E402


class FieldSeasonsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        c1, c2 = Cluster(name="Кластер А"), Cluster(name="Кластер Б")
        db.session.add_all([c1, c2])
        db.session.flush()
        co1 = Company(name="Підприємство А", cluster_id=c1.id)
        co2 = Company(name="Підприємство Б", cluster_id=c2.id)
        cu1, cu2 = Culture(name="Пшениця"), Culture(name="Соняшник")
        db.session.add_all([co1, co2, cu1, cu2])
        db.session.flush()
        field = Field(
            name="СТАРЕ 001", cluster_id=c1.id, company_id=co1.id,
            culture_id=cu1.id, area=100.0, is_active=True,
        )
        db.session.add(field)
        db.session.commit()
        self.field_id = field.id
        self.cluster_a, self.cluster_b = c1.id, c2.id
        self.company_a, self.company_b = co1.id, co2.id
        self.crop_a, self.crop_b = cu1.id, cu2.id
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def set_year(self, year):
        result = self.client.get(
            "/fields/select-season", query_string={"year": year, "next": "/fields"}
        )
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.location, "/fields")

    def test_legacy_field_is_not_invented_in_a_year(self):
        self.assertEqual(Season.query.count(), 2)
        page = self.client.get("/fields")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="global-season-select"', html)
        self.assertIn("Постійний каталог", html)
        self.assertIn("СТАРЕ 001", html)
        self.assertEqual(FieldSeason.query.count(), 0)
        self.assertEqual(Field.query.count(), 1)
        self.assertEqual(self.client.get("/fields/seasons").status_code, 200)

    def test_create_field_uses_directory_links_and_validates_cluster(self):
        bad = self.client.post("/fields/create", data={
            "name": "TEST 002", "cluster": self.cluster_b,
            "company": self.company_a, "area": "80.00", "culture": self.crop_b,
        })
        self.assertEqual(bad.status_code, 200)
        self.assertIn("не належить до вибраного кластера", bad.get_data(as_text=True))
        self.assertEqual(Field.query.count(), 1)

        response = self.client.post("/fields/create", data={
            "name": " TEST   002 ", "cluster": self.cluster_a,
            "company": self.company_a, "area": "80.00", "culture": self.crop_b,
        })
        self.assertEqual(response.status_code, 302)
        field = Field.query.filter_by(name="TEST 002").one()
        target = FieldSeason.query.filter_by(field_id=field.id).one()
        self.assertEqual(target.season.year, 2027)
        self.assertEqual(target.area, Decimal("80.00"))
        self.assertEqual(target.planted_area, Decimal("80.00"))
        self.assertEqual(target.plantings[0].culture_id, self.crop_b)

        duplicate = self.client.post("/fields/create", data={
            "name": "test 002", "cluster": self.cluster_a,
            "company": self.company_a, "area": "70.00",
        })
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(Field.query.count(), 2)

    def test_new_rotations_are_isolated_and_do_not_rewrite_legacy_fields(self):
        old = db.session.get(Field, self.field_id)
        self.set_year(2026)
        assigned = self.client.post(f"/fields/{old.id}/season", data={
            "field-cluster": self.cluster_a,
            "field-company": self.company_a,
            "field-area": "90.00",
        })
        self.assertEqual(assigned.status_code, 302)
        self.client.post(f"/fields/{old.id}/plantings", data={
            "plant-culture": self.crop_a, "plant-area": "60.00",
        })
        too_large = self.client.post(f"/fields/{old.id}/plantings", data={
            "plant-culture": self.crop_b, "plant-area": "40.00",
        })
        self.assertEqual(too_large.status_code, 302)
        record = FieldSeason.query.join(Season).filter(
            FieldSeason.field_id == old.id, Season.year == 2026
        ).one()
        self.assertEqual(record.planted_area, Decimal("60.00"))
        self.assertEqual(len(record.plantings), 1)

        self.set_year(2027)
        self.client.post(f"/fields/{old.id}/season", data={
            "field-cluster": self.cluster_b,
            "field-company": self.company_b,
            "field-area": "105.00",
        })
        self.client.post(f"/fields/{old.id}/plantings", data={
            "plant-culture": self.crop_b, "plant-area": "105.00",
        })
        latest = FieldSeason.query.join(Season).filter(
            FieldSeason.field_id == old.id, Season.year == 2027
        ).one()
        self.assertEqual(latest.company_id, self.company_b)
        self.assertEqual(latest.plantings[0].culture_id, self.crop_b)
        db.session.refresh(old)
        self.assertEqual(old.area, 100.0)
        self.assertEqual(old.company_id, self.company_a)
        self.assertEqual(old.culture_id, self.crop_a)
        self.assertEqual(record.area, Decimal("90.00"))
        self.assertEqual(record.plantings[0].culture_id, self.crop_a)

        detail = self.client.get(f"/fields/{old.id}").get_data(as_text=True)
        self.assertIn("Історія поля", detail)
        self.assertIn("105.00", detail)
        self.assertIn("90.00", detail)
        self.assertEqual(self.client.get("/fields", query_string={
            "culture": self.crop_b,
        }).status_code, 200)

    def test_copy_only_into_empty_year_and_closed_year_rejects_edit(self):
        self.set_year(2027)
        field = db.session.get(Field, self.field_id)
        self.client.post(f"/fields/{field.id}/season", data={
            "field-cluster": self.cluster_a,
            "field-company": self.company_a, "field-area": "50.00",
        })
        self.client.post(f"/fields/{field.id}/plantings", data={
            "plant-culture": self.crop_a, "plant-area": "45.00",
        })
        self.assertEqual(self.client.post("/fields/seasons/create", data={
            "new-year": 2028,
        }).status_code, 302)
        self.assertEqual(self.client.post("/fields/seasons/2028/copy").status_code, 302)
        target = FieldSeason.query.join(Season).filter(
            Season.year == 2028, FieldSeason.field_id == field.id
        ).one()
        self.assertEqual(target.planted_area, Decimal("45.00"))
        self.assertEqual(self.client.post("/fields/seasons/2028/copy").status_code, 302)
        self.assertEqual(FieldSeason.query.filter_by(season_id=target.season_id).count(), 1)

        self.assertEqual(self.client.post("/fields/seasons/2028/toggle").status_code, 302)
        self.set_year(2028)
        forbidden = self.client.post(f"/fields/{field.id}/season", data={
            "field-cluster": self.cluster_a,
            "field-company": self.company_a, "field-area": "55.00",
        })
        self.assertEqual(forbidden.status_code, 409)
        self.assertEqual(target.area, Decimal("50.00"))

    def test_archiving_never_erases_permanent_or_seasonal_history(self):
        field = db.session.get(Field, self.field_id)
        self.client.post(f"/fields/{field.id}/season", data={
            "field-cluster": self.cluster_a, "field-company": self.company_a,
            "field-area": "100.00",
        })
        self.assertEqual(self.client.post(f"/fields/{field.id}/delete").status_code, 302)
        db.session.refresh(field)
        self.assertFalse(field.is_active)
        self.assertEqual(FieldSeason.query.filter_by(field_id=field.id).count(), 1)
        self.assertEqual(self.client.post("/fields/wipe").status_code, 403)


if __name__ == "__main__":
    unittest.main()
