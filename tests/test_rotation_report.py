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

    def test_wide_excel_layout_and_no_top_filter_controls(self):
        menu = self.client.get("/structure")
        self.assertEqual(menu.status_code, 200)
        self.assertIn("/structure/rotation", menu.get_data(as_text=True))
        page = self.client.get("/structure/rotation")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Підприємство", html)
        self.assertIn("Номер поля", html)
        for year in (2020, 2021, 2026, 2027, 2028):
            self.assertIn('data-rotation-year="' + str(year) + '"', html)
        self.assertIn("АКПР 001", html)
        self.assertIn("МТ2 001", html)  # archived history must remain
        self.assertIn("100,00", html)
        self.assertIn("Пшениця озима", html)
        self.assertNotIn('data-rot-param=', html)
        self.assertNotIn("rotation-filter-card", html)
        self.assertNotIn('data-rot-page=', html)
        self.assertNotIn("Кластери", html)
        self.assertNotIn("За масивами", html)
        self.assertNotIn("Площа від, га", html)
        self.assertNotIn("Зберегти зміни", html)

    def test_year_specific_crop_filter_shows_full_history(self):
        page = self.client.get("/structure/rotation", query_string={
            "crop_2020": str(self.sunflower.id)
        })
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Полів: <strong>1</strong>", html)
        self.assertIn("АКПР 001", html)
        self.assertNotIn("<td class=\"rot-field\">АКПР 002</td>", html)
        self.assertIn("90,00", html)  # 2021 is still visible
        self.assertIn("Пшениця озима", html)
        self.assertIn('class="rotation-crop-filter is-active"', html)

    def test_filters_combine_across_years_and_or_within_year(self):
        # A had sunflower in 2020 but wheat in 2021. B was reversed.
        both = self.client.get("/structure/rotation", query_string=[
            ("crop_2020", str(self.sunflower.id)),
            ("crop_2021", str(self.wheat.id)),
        ])
        self.assertIn("Полів: <strong>1</strong>", both.get_data(as_text=True))
        self.assertIn("АКПР 001", both.get_data(as_text=True))

        impossible = self.client.get("/structure/rotation", query_string=[
            ("crop_2020", str(self.sunflower.id)),
            ("crop_2021", str(self.sunflower.id)),
        ])
        self.assertIn("Полів: <strong>0</strong>", impossible.get_data(as_text=True))

        # Choosing several crops inside 2020 is an OR.
        many = self.client.get("/structure/rotation", query_string=[
            ("crop_2020", str(self.sunflower.id)),
            ("crop_2020", str(self.wheat.id)),
        ])
        self.assertIn("Полів: <strong>2</strong>", many.get_data(as_text=True))

    def test_excel_blank_and_invalid_filter_do_not_expand_results(self):
        blank = self.client.get("/structure/rotation", query_string={
            "crop_2020": "__empty__"
        })
        text = blank.get_data(as_text=True)
        self.assertIn("Полів: <strong>2</strong>", text)
        self.assertIn("АКБ 999", text)
        self.assertIn("МТ2 001", text)
        self.assertNotIn("<td class=\"rot-field\">АКПР 001</td>", text)

        empty = self.client.get("/structure/rotation", query_string={
            "crop_2020": "__none__"
        })
        self.assertIn("Полів: <strong>0</strong>", empty.get_data(as_text=True))
        malformed = self.client.get("/structure/rotation", query_string={
            "crop_2020": "not-a-real-culture"
        })
        self.assertIn("Полів: <strong>0</strong>", malformed.get_data(as_text=True))

    def test_ajax_options_for_each_year_and_csv_respects_filters(self):
        ajax = self.client.get("/structure/rotation", headers={
            "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
        })
        self.assertEqual(ajax.status_code, 200)
        self.assertEqual(ajax.json["field_count"], 4)
        self.assertIn('data-rotation-year="2020"', ajax.json["html"])
        opts = ajax.json["filters"]
        self.assertIn("2020", opts)
        self.assertIn("2028", opts)
        names = {x["name"] for x in opts["2020"]["options"]}
        self.assertIn("Соняшник", names)
        self.assertIn("Пшениця озима", names)
        self.assertIn("(Порожньо)", names)

        response = self.client.get("/structure/rotation/csv", query_string={
            "crop_2020": str(self.sunflower.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        raw = response.get_data(as_text=True)
        self.assertTrue(raw.startswith("\ufeff"))
        records = list(csv.reader(io.StringIO(raw.lstrip("\ufeff")), delimiter=";"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0][:2], ["Підприємство", "Номер поля"])
        self.assertEqual(records[1][1], "АКПР 001")
        self.assertEqual(records[1][2:6],
                         ["100,00", "Соняшник", "90,00", "Пшениця озима"])

    def test_read_only_and_export_not_limited_to_first_page(self):
        before = (Field.query.count(), FieldSeason.query.count(),
                  FieldPlanting.query.count())
        self.assertEqual(self.client.post("/structure/rotation").status_code, 405)
        self.assertEqual(self.client.post("/structure/rotation/csv").status_code, 405)

        for i in range(55):
            field = self.add_field(f"ДОД {i:03d}", self.company1)
            self.sow(field, 2020, "1.00", [(self.sunflower, "1.00")])
        db.session.commit()

        page = self.client.get("/structure/rotation", query_string={
            "crop_2020": str(self.sunflower.id)
        }).get_data(as_text=True)
        self.assertIn("Полів: <strong>56</strong>", page)
        self.assertIn("ДОД 054", page)
        self.assertIn("155,00", page)  # 100 + 55

        response = self.client.get("/structure/rotation/csv", query_string={
            "crop_2020": str(self.sunflower.id)
        })
        records = list(csv.reader(io.StringIO(
            response.get_data(as_text=True).lstrip("\ufeff")
        ), delimiter=";"))
        self.assertEqual(len(records), 1 + 56)
        self.assertEqual(Field.query.count(), before[0] + 55)
        self.assertEqual(FieldSeason.query.count(), before[1] + 55)
        self.assertEqual(FieldPlanting.query.count(), before[2] + 55)


if __name__ == "__main__":
    unittest.main()
