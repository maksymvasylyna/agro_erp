"""Tests run against disposable in-memory SQLite; never touch Render PostgreSQL."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-only-strong-secret-key-32-characters"
os.environ["SEASON_ADMIN_PASSWORD"] = "test-only-admin-password-32-chars"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from modules.reference.clusters.models import Cluster  # noqa: E402
from modules.reference.companies.models import Company  # noqa: E402
from modules.reference.cultures.models import Culture  # noqa: E402
from modules.reference.fields.field_models import Field  # noqa: E402
from modules.structure.seasons.models import Season, FieldSeason, FieldPlanting  # noqa: E402


class SeasonWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        cluster = Cluster(name="Тестовий кластер")
        db.session.add(cluster)
        db.session.flush()
        company = Company(name="Тестове підприємство", cluster_id=cluster.id)
        culture_a = Culture(name="Пшениця")
        culture_b = Culture(name="Соняшник")
        db.session.add_all([company, culture_a, culture_b])
        db.session.flush()
        field = Field(name="TEST-001", is_active=True, cluster_id=cluster.id,
                      company_id=company.id, area=100.0, culture_id=culture_a.id)
        db.session.add(field)
        db.session.commit()
        self.field_id = field.id
        self.culture_a = culture_a.id
        self.culture_b = culture_b.id
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login(self):
        response = self.client.post("/seasons/login", data={
            "password": os.environ["SEASON_ADMIN_PASSWORD"]
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_writes_require_login(self):
        response = self.client.post("/seasons/create", data={"new-year": 2026})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Season.query.count(), 0)

    def test_create_copy_edit_seasons_without_touching_legacy_field(self):
        self.login()
        self.assertEqual(self.client.post("/seasons/create", data={"new-year": 2026}).status_code, 302)
        self.assertEqual(self.client.post("/seasons/create", data={"new-year": 2027}).status_code, 302)
        self.assertEqual(self.client.post("/seasons/2026/fields", data={
            "field-field_id": self.field_id, "field-area": "100.00"
        }).status_code, 302)
        source_fs = FieldSeason.query.join(Season).filter(Season.year == 2026).one()
        response = self.client.post("/seasons/fields/%s/plantings" % source_fs.id, data={
            "plant-culture_id": self.culture_a, "plant-area": "65.00"
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post("/seasons/2027/copy").status_code, 302)
        target_fs = FieldSeason.query.join(Season).filter(Season.year == 2027).one()
        self.assertEqual(target_fs.area, Decimal("100.00"))
        self.assertEqual(target_fs.planted_area, Decimal("65.00"))
        target_crop = target_fs.plantings[0]

        response = self.client.post("/seasons/plantings/%s/edit" % target_crop.id, data={
            "plant-culture_id": self.culture_b, "plant-area": "80.00"
        })
        self.assertEqual(response.status_code, 302)
        db.session.refresh(target_crop)
        self.assertEqual(target_crop.culture_id, self.culture_b)
        self.assertEqual(target_crop.area, Decimal("80.00"))
        self.assertEqual(source_fs.plantings[0].culture_id, self.culture_a)
        self.assertEqual(source_fs.plantings[0].area, Decimal("65.00"))

        response = self.client.post("/seasons/fields/%s/plantings" % target_fs.id, data={
            "plant-culture_id": self.culture_a, "plant-area": "25.00"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_fs.planted_area, Decimal("80.00"))

        legacy_field = db.session.get(Field, self.field_id)
        self.assertEqual(legacy_field.area, 100.0)
        self.assertEqual(legacy_field.culture_id, self.culture_a)
        self.assertEqual(self.client.get("/structure/fields").status_code, 200)
        self.assertEqual(self.client.get("/summary_structure/").status_code, 200)

    def test_duplicate_field_and_clone_overwrite_are_rejected(self):
        self.login()
        self.client.post("/seasons/create", data={"new-year": 2026})
        self.client.post("/seasons/create", data={"new-year": 2027})
        data = {"field-field_id": self.field_id, "field-area": "30.00"}
        self.client.post("/seasons/2026/fields", data=data)
        self.client.post("/seasons/2026/fields", data=data)
        self.assertEqual(FieldSeason.query.count(), 1)
        self.assertEqual(self.client.post("/seasons/2027/copy").status_code, 302)
        self.assertEqual(self.client.post("/seasons/2027/copy").status_code, 409)
        self.assertEqual(FieldSeason.query.count(), 2)

    def test_summary_year_switch_keeps_report_layout_and_filters(self):
        self.login()
        for year in (2024, 2025):
            self.assertEqual(self.client.post(
                "/seasons/create", data={"new-year": year}
            ).status_code, 302)
        for year, area, crop in (
            (2024, "100.00", self.culture_a),
            (2025, "90.00", self.culture_b),
        ):
            self.client.post(
                f"/seasons/{year}/fields",
                data={"field-field_id": self.field_id, "field-area": area},
            )
            field_season = FieldSeason.query.join(Season).filter(Season.year == year).one()
            self.client.post(
                f"/seasons/fields/{field_season.id}/plantings",
                data={"plant-culture_id": crop, "plant-area": area},
            )

        cluster_id = Cluster.query.one().id
        target = f"/summary_structure/?cluster_id={cluster_id}"
        change = self.client.get(
            "/seasons/select", query_string={"year": 2024, "next": target}
        )
        self.assertEqual(change.status_code, 302)
        self.assertEqual(change.location, target)

        summary = self.client.get(target)
        self.assertEqual(summary.status_code, 200)
        text = summary.get_data(as_text=True)
        self.assertIn("Структура посівів за культурами — урожай 2024", text)
        self.assertIn('scope="col">Пшениця</th>', text)
        self.assertNotIn('scope="col">Соняшник</th>', text)
        self.assertIn("100,00", text)
        self.assertNotIn("90,00", text)
        self.assertNotIn("Зведена площа за підприємствами та роками", text)
        self.assertNotIn("<details", text)

        next_year = self.client.get(
            "/seasons/select", query_string={"year": 2025, "next": target},
            follow_redirects=True,
        )
        self.assertEqual(next_year.status_code, 200)
        text = next_year.get_data(as_text=True)
        self.assertIn("Структура посівів за культурами — урожай 2025", text)
        self.assertIn('scope="col">Соняшник</th>', text)
        self.assertNotIn('scope="col">Пшениця</th>', text)
        self.assertIn("90,00", text)
        self.assertNotIn("100,00", text)
        self.assertNotIn("<details", text)

    def test_fields_multi_filters_combine_or_within_and_across_dimensions(self):
        """Two clusters, multiple companies and crops, and split-field hectares."""
        from urllib.parse import urlencode

        cluster_a = Cluster.query.one()
        company_a = Company.query.one()
        cluster_b = Cluster(name="Інший кластер")
        db.session.add(cluster_b)
        db.session.flush()
        company_b = Company(name="Підприємство Б", cluster_id=cluster_b.id)
        company_c = Company(name="Підприємство В", cluster_id=cluster_a.id)
        company_d = Company(name="Підприємство Г", cluster_id=cluster_b.id)
        db.session.add_all([company_b, company_c, company_d])
        db.session.flush()

        season = Season(year=2026)
        db.session.add(season)
        db.session.flush()

        def add_field(code, company, cluster, area, crops):
            field = Field(name=code, company_id=company.id,
                          cluster_id=cluster.id, area=float(area),
                          is_active=True, culture_id=crops[0][0])
            db.session.add(field)
            db.session.flush()
            fs = FieldSeason(season_id=season.id, field_id=field.id,
                             company_id=company.id, cluster_id=cluster.id,
                             area=Decimal(str(area)))
            db.session.add(fs)
            db.session.flush()
            for crop, ha in crops:
                db.session.add(FieldPlanting(field_season_id=fs.id,
                                             culture_id=crop, area=Decimal(str(ha))))

        add_field("A", company_a, cluster_a, 100,
                  [(self.culture_a, 40), (self.culture_b, 60)])
        add_field("B", company_b, cluster_b, 75,
                  [(self.culture_a, 50), (self.culture_b, 25)])
        add_field("C", company_c, cluster_a, 35, [(self.culture_b, 35)])
        add_field("D", company_d, cluster_b, 15, [(self.culture_a, 15)])
        db.session.commit()

        # Default is all values, including multiple crop rows on a split field.
        all_response = self.client.get("/structure/fields")
        html = all_response.get_data(as_text=True)
        self.assertEqual(all_response.status_code, 200)
        self.assertIn("Знайдено посівів: <strong>6</strong>", html)
        self.assertIn("225.00 га", html)
        self.assertIn("Обрати все", html)
        self.assertIn('data-filter-key="clusters"', html)
        self.assertIn('data-filter-key="companies"', html)
        self.assertIn('data-filter-key="cultures"', html)
        self.assertNotIn("Фільтрувати</button>", html)

        # OR inside companies; AND with culture; independent of cluster.
        query = [
            ("companies", str(company_a.id)),
            ("companies", str(company_b.id)),
            ("cultures", str(self.culture_a)),
        ]
        response = self.client.get("/structure/fields", query_string=query)
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Знайдено посівів: <strong>2</strong>", text)
        self.assertIn("90.00 га", text)
        self.assertNotIn("225.00 га", text)

        # Add one cluster: only company A remains selected.
        query.append(("clusters", str(cluster_a.id)))
        response = self.client.get("/structure/fields", query_string=query)
        self.assertIn("40.00 га", response.get_data(as_text=True))
        self.assertIn("Знайдено посівів: <strong>1</strong>",
                      response.get_data(as_text=True))

        # Two cultures selected explicitly are equivalent to all crops.
        both_crops = self.client.get("/structure/fields", query_string=[
            ("cultures", str(self.culture_a)),
            ("cultures", str(self.culture_b)),
        ])
        self.assertIn("225.00 га", both_crops.get_data(as_text=True))

        # Explicit zero or an invalid id must never mean 'all'.
        for value in ("__none__", "9999999999", "not-a-number"):
            response = self.client.get("/structure/fields", query_string={
                "cultures": value
            })
            self.assertIn("Знайдено посівів: <strong>0</strong>",
                          response.get_data(as_text=True))

        # AJAX returns only the live-updated table, not a full page.
        response = self.client.get(
            "/structure/fields", query_string=query,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        self.assertIn('id="field-results"', markup)
        self.assertNotIn("<html", markup)
        self.assertIn("40.00 га", markup)

    def test_season_redirect_rejects_external_urls(self):
        db.session.add(Season(year=2026))
        db.session.commit()
        response = self.client.get(
            "/seasons/select", query_string={
                "year": 2026, "next": "https://example.com/fake"
            }
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/seasons/"))


if __name__ == "__main__":
    unittest.main()
