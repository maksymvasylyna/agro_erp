"""Read-only multi-year crop rotation view integration tests (isolated SQLite)."""
import csv
import io
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-only-crop-rotation-view-2026"
os.environ.pop("AGROERP_FIELD_HISTORY_IMPORT", None)

from app import create_app
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting


class RotationReportTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.session.add_all([Cluster(name="Кластер 1"), Cluster(name="Кластер 2")])
        db.session.flush()
        self.cluster1, self.cluster2 = [c.id for c in Cluster.query.order_by(Cluster.id).all()]
        db.session.add_all([
            Company(name="Агроконтракт-Н 2021 ТОВ", cluster_id=self.cluster1),
            Company(name="Митрофанівська ПП", cluster_id=self.cluster2),
        ])
        db.session.add_all([
            Culture(name="Соняшник"), Culture(name="Пшениця озима"),
            Culture(name="Кукурудза на зерно"),
        ])
        db.session.add_all([Season(year=2020), Season(year=2021), Season(year=2028)])
        db.session.flush()
        self.company1 = Company.query.filter_by(name="Агроконтракт-Н 2021 ТОВ").one()
        self.company2 = Company.query.filter_by(name="Митрофанівська ПП").one()
        self.sunflower = Culture.query.filter_by(name="Соняшник").one()
        self.wheat = Culture.query.filter_by(name="Пшениця озима").one()
        self.corn = Culture.query.filter_by(name="Кукурудза на зерно").one()
        self.field_a = self.add_field("АКПР 001", self.company1)
        self.field_b = self.add_field("АКПР 002", self.company1)
        self.field_c = self.add_field("МТ2 001", self.company2, active=False)
        self.field_d = self.add_field("АКБ 999", self.company1)

        self.sow(self.field_a, 2020, "100.00", [(self.sunflower, "100.00")])
        self.sow(self.field_a, 2021, "90.00", [(self.wheat, "90.00")])
        self.sow(self.field_a, 2027, "88.00", [
            (self.wheat, "33.00"), (self.sunflower, "55.00")
        ])
        self.sow(self.field_b, 2020, "50.00", [(self.wheat, "50.00")])
        self.sow(self.field_b, 2021, "50.00", [(self.sunflower, "50.00")])
        self.sow(self.field_c, 2021, "60.00", [(self.corn, "60.00")])
        self.sow(self.field_c, 2028, "61.00", [(self.corn, "61.00")])
        self.sow(self.field_d, 2026, "20.00", [])  # physical area without planting
        db.session.commit()
        self.client = self.app.test_client()

    def add_field(self, name, company, active=True):
        field = Field(
            name=name, company_id=company.id, cluster_id=company.cluster_id,
            is_active=active, area=999, culture_id=self.wheat.id,
        )
        db.session.add(field)
        db.session.flush()
        return field

    def sow(self, field, year, area, crops):
        season = Season.query.filter_by(year=year).one()
        fs = FieldSeason(
            season_id=season.id, field_id=field.id,
            company_id=field.company_id, cluster_id=field.cluster_id,
            area=Decimal(area),
        )
        db.session.add(fs)
        db.session.flush()
        for culture, area in crops:
            db.session.add(FieldPlanting(
                field_season_id=fs.id, culture_id=culture.id,
                area=Decimal(area),
            ))

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_structure_menu_and_multi_year_view(self):
        menu = self.client.get("/structure")
        self.assertEqual(menu.status_code, 200)
        self.assertIn("/structure/rotation", menu.get_data(as_text=True))
        response = self.client.get("/structure/rotation")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("2020", html)
        self.assertIn("2021", html)
        self.assertIn("2027", html)
        self.assertIn("2028", html)  # dynamically read from Season
        self.assertIn("АКПР 001", html)
        self.assertIn("МТ2 001", html)  # archived field with rotation history
        self.assertIn("лише для перегляду", html)
        self.assertNotIn("Зберегти зміни", html)
        self.assertNotIn("Видалити поле", html)
        self.assertIn("100,00", html)
        self.assertIn("Пшениця озима", html)

    def test_crop_in_selected_year_retains_whole_rotation(self):
        params = {"crop_year": 2020, "cultures": self.sunflower.id}
        response = self.client.get("/structure/rotation", query_string=params)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("АКПР 001", html)
        self.assertNotIn("<strong>АКПР 002</strong>", html)
        self.assertIn("90,00", html)  # later wheat remains visible
        self.assertIn("Пшениця озима", html)
        self.assertIn("Полів: 1", html)

        # In any year both field A and B match sunflower.
        every_year = self.client.get("/structure/rotation", query_string={
            "cultures": self.sunflower.id,
        }).get_data(as_text=True)
        self.assertIn("<strong>АКПР 001</strong>", every_year)
        self.assertIn("<strong>АКПР 002</strong>", every_year)

    def test_cluster_company_and_mass_cascade(self):
        response = self.client.get("/structure/rotation", query_string={
            "clusters": self.cluster1, "companies": self.company1.id,
            "masses": "АКПР", "view": "masses",
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("АКПР", html)
        self.assertIn("2 полів", html)
        self.assertIn("150,00", html)  # 2020: 100 + 50
        self.assertIn("140,00", html)  # 2021: 90 + 50
        self.assertNotIn("<strong>МТ2 001</strong>", html)

        selected = self.client.get("/structure/rotation", query_string={
            "clusters": self.cluster1, "companies": self.company2.id,
        }, headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json["field_count"], 0)
        self.assertEqual(len(selected.json["facets"]["companies"]), 1)

    def test_area_bounds_match_same_year_and_query_filter(self):
        # Field A: 100 / 90 / 88; the requested 92..95 range never occurs.
        impossible = self.client.get("/structure/rotation", query_string={
            "q": "АКПР 001", "area_min": 92, "area_max": 95,
        })
        self.assertIn("Полів: 0", impossible.get_data(as_text=True))
        valid = self.client.get("/structure/rotation", query_string={
            "q": "АКПР 001", "area_min": 85, "area_max": 95,
        })
        self.assertIn("Полів: 1", valid.get_data(as_text=True))
        # Field D has an area but no planting; still show it with no crop filter.
        blank = self.client.get("/structure/rotation", query_string={"q": "АКБ 999"})
        self.assertIn("Полів: 1", blank.get_data(as_text=True))

    def test_ajax_and_explicit_empty_facets(self):
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        response = self.client.get("/structure/rotation", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["field_count"], 4)
        self.assertIn("data-rot-page", response.json["html"])
        self.assertIn("clusters", response.json["facets"])
        self.assertEqual(
            {x["name"] for x in response.json["facets"]["cultures"]},
            {"Соняшник", "Пшениця озима", "Кукурудза на зерно"},
        )
        empty = self.client.get("/structure/rotation", query_string={
            "clusters": "__none__",
        }, headers=headers)
        self.assertEqual(empty.json["field_count"], 0)
        malformed = self.client.get("/structure/rotation", query_string={
            "clusters": "not-an-id",
        }, headers=headers)
        self.assertEqual(malformed.json["field_count"], 0)

    def test_csv_matches_filters_and_is_excel_friendly(self):
        response = self.client.get("/structure/rotation/csv", query_string={
            "year_from": 2020, "year_to": 2021, "q": "АКПР 001",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        text = response.get_data(as_text=True)
        self.assertTrue(text.startswith("\ufeff"))
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][-4:], [
            "2020 Площа, га", "2020 Культура", "2021 Площа, га", "2021 Культура"
        ])
        self.assertEqual(rows[1][-4:], ["100,00", "Соняшник", "90,00", "Пшениця озима"])
        self.assertEqual(rows[1][3], "АКПР 001")

    def test_read_only_and_malformed_filters(self):
        before = (Field.query.count(), FieldSeason.query.count(), FieldPlanting.query.count())
        self.assertEqual(self.client.post("/structure/rotation").status_code, 405)
        self.assertEqual(self.client.post("/structure/rotation/csv").status_code, 405)
        for params in [
            {"year_from": 2017}, {"year_from": 2028, "year_to": 2020},
            {"crop_year": 2020, "year_from": 2021}, {"area_min": "-2"},
            {"area_min": "NaN"}, {"view": "evil"}, {"page": "-1"},
            {"per_page": "999999"},
        ]:
            self.assertEqual(self.client.get("/structure/rotation", query_string=params).status_code, 400, params)
        self.client.get("/structure/rotation")
        self.client.get("/structure/rotation/csv")
        self.assertEqual(
            (Field.query.count(), FieldSeason.query.count(), FieldPlanting.query.count()),
            before,
        )

    def test_pagination_only_changes_visible_page_not_totals(self):
        for i in range(55):
            extra = self.add_field(f"ДОД {i:03d}", self.company1)
            self.sow(extra, 2020, "1.00", [(self.sunflower, "1.00")])
        db.session.commit()
        html = self.client.get("/structure/rotation", query_string={
            "per_page": 50, "page": 2,
        }).get_data(as_text=True)
        self.assertIn("Сторінка 2 із 2", html)
        self.assertIn("Полів: 59", html)
        self.assertIn("Показано рядків: 9 із 59", html)
        self.assertIn("205,00", html)  # 2020: 100 + 50 + 55
        csv_response = self.client.get("/structure/rotation/csv", query_string={
            "per_page": 50, "page": 2, "year_from": 2020, "year_to": 2020
        })
        rows = list(csv.reader(io.StringIO(
            csv_response.get_data(as_text=True).lstrip("\ufeff")
        ), delimiter=";"))
        # All 2020 fields, not only the nine on page two.
        self.assertEqual(len(rows), 1 + 57)


if __name__ == "__main__":
    unittest.main()
