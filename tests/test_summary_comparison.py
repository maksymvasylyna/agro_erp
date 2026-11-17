"""Year comparisons in the area summary use disposable, isolated SQLite only."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-summary-comparison-not-production"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from modules.reference.clusters.models import Cluster  # noqa: E402
from modules.reference.companies.models import Company  # noqa: E402
from modules.reference.cultures.models import Culture  # noqa: E402
from modules.reference.fields.field_models import Field  # noqa: E402
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting  # noqa: E402
from modules.structure.summary_structure.routes import _multi_comparison_context  # noqa: E402


class SummaryYearComparisonTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()

        a, b = Cluster(name="Кластер А"), Cluster(name="Кластер Б")
        db.session.add_all([a, b])
        db.session.flush()
        ca = Company(name="Підприємство А", cluster_id=a.id)
        cb = Company(name="Підприємство Б", cluster_id=b.id)
        wheat = Culture(name="Пшениця")
        sun = Culture(name="Соняшник")
        corn = Culture(name="Кукурудза")
        db.session.add_all([ca, cb, wheat, sun, corn])
        db.session.flush()
        fa = Field(name="A-001", cluster_id=a.id, company_id=ca.id,
                   culture_id=wheat.id, area=999, is_active=True)
        fb = Field(name="Б-001", cluster_id=b.id, company_id=cb.id,
                   culture_id=sun.id, area=999, is_active=True)
        fc = Field(name="Б-002", cluster_id=b.id, company_id=cb.id,
                   culture_id=corn.id, area=999, is_active=True)
        year24 = Season(year=2024)
        year25 = Season(year=2025)
        db.session.add_all([fa, fb, fc, year24, year25])
        db.session.flush()

        year26 = Season.query.filter_by(year=2026).one()
        year27 = Season.query.filter_by(year=2027).one()
        records = [
            (year24, fa, a, ca, [(wheat, "20.00")]),
            (year24, fb, b, cb, [(sun, "30.00")]),
            (year25, fa, a, ca, [(wheat, "60.00")]),
            (year26, fa, a, ca, [(wheat, "50.00"), (sun, "25.00")]),
            (year25, fb, b, cb, [(sun, "80.00")]),
            (year26, fc, b, cb, [(corn, "100.00")]),
        ]
        for season, field, cluster, company, crops in records:
            planted = sum((Decimal(area) for _, area in crops), Decimal("0.00"))
            fs = FieldSeason(season_id=season.id, field_id=field.id,
                             cluster_id=cluster.id, company_id=company.id,
                             area=planted)
            db.session.add(fs)
            db.session.flush()
            for culture, area in crops:
                db.session.add(FieldPlanting(
                    field_season_id=fs.id, culture_id=culture.id, area=Decimal(area),
                ))
        db.session.commit()
        self.s24, self.s25, self.s26, self.s27 = year24, year25, year26, year27
        self.cluster_a, self.cluster_b = a.id, b.id
        self.client = self.app.test_client()
        change = self.client.get(
            "/fields/select-season",
            query_string={"year": 2026, "next": "/summary_structure/"},
        )
        self.assertEqual(change.status_code, 302)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def get_comparison(self, *years, cluster=None):
        params = [("years", year) for year in years]
        if cluster is not None:
            params.append(("cluster_id", cluster))
        return self.client.get("/summary_structure/", query_string=params)

    def test_multiple_checkbox_years_are_compared_against_global_2026(self):
        result = _multi_comparison_context(self.s26, [self.s25, self.s24], None)
        self.assertEqual(result["base_year"], 2026)
        self.assertEqual(result["selected_years"], [2025, 2024])
        total = result["overall"]
        self.assertEqual(total["base"], Decimal("175.00"))
        self.assertEqual(total["compared"][0]["year"], 2025)
        self.assertEqual(total["compared"][0]["area"], Decimal("140.00"))
        self.assertEqual(total["compared"][0]["difference"], Decimal("35.00"))
        self.assertEqual(total["compared"][0]["percent"], Decimal("25.0"))
        self.assertEqual(total["compared"][1]["year"], 2024)
        self.assertEqual(total["compared"][1]["area"], Decimal("50.00"))
        self.assertEqual(total["compared"][1]["difference"], Decimal("125.00"))
        self.assertEqual(total["compared"][1]["percent"], Decimal("250.0"))
        crops = {entry["name"]: entry for entry in result["crop_rows"]}
        self.assertEqual(set(crops), {"Пшениця", "Соняшник", "Кукурудза"})
        self.assertEqual(crops["Пшениця"]["base"], Decimal("50.00"))
        self.assertEqual(crops["Пшениця"]["compared"][0]["area"], Decimal("60.00"))
        self.assertEqual(crops["Пшениця"]["compared"][1]["area"], Decimal("20.00"))
        self.assertEqual(crops["Кукурудза"]["compared"][0]["area"], Decimal("0.00"))
        self.assertIsNone(crops["Кукурудза"]["compared"][0]["percent"])
        self.assertEqual(crops["Кукурудза"]["base"], Decimal("100.00"))

    def test_multiselect_html_and_selected_checkboxes(self):
        response = self.get_comparison(2024, 2025)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="year-multiselect"', html)
        self.assertIn('id="compare-year-checkboxes"', html)
        self.assertIn('type="checkbox" name="years"', html)
        self.assertIn('value="2025" checked', html)
        self.assertIn('value="2024" checked', html)
        self.assertNotIn('id="year_a"', html)
        self.assertNotIn('id="year_b"', html)
        self.assertIn("Порівняння посівних площ: 2026 з 2025, 2024", html)
        self.assertIn("Основний сезон — 2026", html)
        self.assertIn('id="comparison-by-crop"', html)
        self.assertIn('id="comparison-by-company"', html)
        self.assertIn("+125,00", html)
        self.assertIn("250,0%", html)
        self.assertIn("Кукурудза", html)
        self.assertIn("Вибрати всі", html)
        self.assertIn("Очистити", html)
        self.assertIn("PDF поточного сезону", html)
        self.assertIn("Закрити порівняння", html)
        self.assertNotIn('id="global-season-select"', html)
        with self.client.session_transaction() as state:
            self.assertEqual(state["harvest_year"], 2026)

    def test_selected_years_sorted_and_filtered_for_each_cluster(self):
        response = self.get_comparison(2024, 2025, cluster=self.cluster_a)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Порівняння посівних площ: 2026 з 2025, 2024", html)
        self.assertIn("Підприємство А", html)
        self.assertNotIn("Підприємство Б", html)
        result = _multi_comparison_context(self.s26, [self.s25, self.s24], self.cluster_a)
        self.assertEqual(result["overall"]["base"], Decimal("75.00"))
        self.assertEqual(result["overall"]["compared"][0]["area"], Decimal("60.00"))
        self.assertEqual(result["overall"]["compared"][1]["area"], Decimal("20.00"))
        result_b = _multi_comparison_context(self.s26, [self.s25, self.s24], self.cluster_b)
        self.assertEqual(result_b["overall"]["base"], Decimal("100.00"))
        self.assertEqual(result_b["overall"]["compared"][0]["area"], Decimal("80.00"))
        self.assertEqual(result_b["overall"]["compared"][1]["area"], Decimal("30.00"))

    def test_single_year_and_empty_year(self):
        single = self.get_comparison(2025)
        self.assertEqual(single.status_code, 200)
        h = single.get_data(as_text=True)
        self.assertIn("Порівняння посівних площ: 2026 з 2025", h)
        self.assertNotIn('value="2024" checked', h)
        empty = self.get_comparison(2027)
        self.assertEqual(empty.status_code, 200)
        e = empty.get_data(as_text=True)
        self.assertIn("Порівняння посівних площ: 2026 з 2027", e)
        result = _multi_comparison_context(self.s26, [self.s27], None)
        self.assertEqual(result["overall"]["compared"][0]["area"], Decimal("0.00"))
        self.assertIsNone(result["overall"]["compared"][0]["percent"])

    def test_global_year_controls_baseline_and_is_not_checkable(self):
        switch = self.client.get(
            "/fields/select-season",
            query_string={"year": 2024, "next": "/summary_structure/"},
        )
        self.assertEqual(switch.status_code, 302)
        response = self.get_comparison(2025, 2026)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Порівняння посівних площ: 2024 з 2026, 2025", html)
        self.assertIn("Основний сезон: 2024", html)
        self.assertNotRegex(html, r'name="years"\\s+value="2024"')
        data = _multi_comparison_context(self.s24, [self.s26, self.s25], None)
        self.assertEqual(data["overall"]["base"], Decimal("50.00"))
        self.assertEqual(data["overall"]["compared"][0]["area"], Decimal("175.00"))
        self.assertEqual(data["overall"]["compared"][1]["area"], Decimal("140.00"))
        with self.client.session_transaction() as state:
            self.assertEqual(state["harvest_year"], 2024)

    def test_invalid_multi_year_selection_is_rejected(self):
        bad = [
            [2026], [2050], ["oops"], [""],
            [2025, 2025], [2025, 2050], [2024, "wrong"],
        ]
        for values in bad:
            response = self.get_comparison(*values)
            self.assertEqual(response.status_code, 400, values)
        with self.client.session_transaction() as state:
            self.assertEqual(state["harvest_year"], 2026)

    def test_closing_comparison_preserves_global_year_and_standard_pdf(self):
        normal = self.client.get("/summary_structure/")
        self.assertEqual(normal.status_code, 200)
        html = normal.get_data(as_text=True)
        self.assertIn('id="open-year-comparison"', html)
        self.assertNotIn('id="year-multiselect"', html)
        self.assertIn("Структура посівів за культурами", html)
        self.assertIn("175,00", html)
        pdf = self.client.get("/summary_structure/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("zagalna_struktura_2026.pdf",
                      pdf.headers["Content-Disposition"])
        compare_pdf = self.client.get(
            "/summary_structure/pdf", query_string=[("years", "2025"), ("years", "2024")]
        )
        self.assertEqual(compare_pdf.status_code, 200)
        self.assertIn("zagalna_struktura_2026.pdf",
                      compare_pdf.headers["Content-Disposition"])
        with self.client.session_transaction() as state:
            self.assertEqual(state["harvest_year"], 2026)

    def test_legacy_single_year_link_stays_anchored_to_global_season(self):
        response = self.client.get("/summary_structure/", query_string={"compare_year": 2025})
        self.assertEqual(response.status_code, 200)
        self.assertIn("2026 з 2025", response.get_data(as_text=True))
        response = self.client.get("/summary_structure/",
                                   query_string={"year_a": 2025, "year_b": 2026})
        self.assertEqual(response.status_code, 200)
        self.assertIn("2026 з 2025", response.get_data(as_text=True))
        bad = self.client.get("/summary_structure/",
                              query_string={"year_a": 2024, "year_b": 2025})
        self.assertEqual(bad.status_code, 400)




if __name__ == "__main__":
    unittest.main()
