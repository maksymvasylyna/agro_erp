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
from modules.structure.summary_structure.routes import _comparison_context  # noqa: E402


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
        year25 = Season(year=2025)
        db.session.add_all([fa, fb, fc, year25])
        db.session.flush()

        year26 = Season.query.filter_by(year=2026).one()
        year27 = Season.query.filter_by(year=2027).one()
        records = [
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
        self.s25, self.s26, self.s27 = year25, year26, year27
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

    def test_comparison_uses_both_years_and_union_of_crops(self):
        rows = _comparison_context(self.s26, self.s25, None)
        self.assertEqual(rows["overall"]["before"], Decimal("140.00"))
        self.assertEqual(rows["overall"]["after"], Decimal("175.00"))
        self.assertEqual(rows["overall"]["difference"], Decimal("35.00"))
        self.assertEqual(rows["overall"]["percent"], Decimal("25.0"))
        crops = {row["name"]: row for row in rows["crop_rows"]}
        self.assertEqual(set(crops), {"Пшениця", "Соняшник", "Кукурудза"})
        self.assertEqual(crops["Пшениця"]["before"], Decimal("60.00"))
        self.assertEqual(crops["Пшениця"]["after"], Decimal("50.00"))
        self.assertEqual(crops["Соняшник"]["before"], Decimal("80.00"))
        self.assertEqual(crops["Соняшник"]["after"], Decimal("25.00"))
        self.assertEqual(crops["Кукурудза"]["before"], Decimal("0.00"))
        self.assertEqual(crops["Кукурудза"]["after"], Decimal("100.00"))
        self.assertIsNone(crops["Кукурудза"]["percent"])
        clusters = {row["name"]: row for row in rows["cluster_rows"]}
        self.assertEqual(clusters["Кластер А"]["after"], Decimal("75.00"))
        self.assertEqual(clusters["Кластер Б"]["before"], Decimal("80.00"))
        self.assertEqual(clusters["Кластер Б"]["after"], Decimal("100.00"))

    def test_comparison_filters_both_years_without_changing_session(self):
        a = _comparison_context(self.s26, self.s25, self.cluster_a)
        self.assertEqual(a["overall"]["before"], Decimal("60.00"))
        self.assertEqual(a["overall"]["after"], Decimal("75.00"))
        self.assertEqual(a["overall"]["difference"], Decimal("15.00"))
        self.assertEqual(a["overall"]["percent"], Decimal("25.0"))
        self.assertEqual(len(a["cluster_rows"]), 1)
        self.assertEqual(a["cluster_rows"][0]["companies"][0]["name"],
                         "Підприємство А")
        b = _comparison_context(self.s26, self.s25, self.cluster_b)
        self.assertEqual(b["overall"]["before"], Decimal("80.00"))
        self.assertEqual(b["overall"]["after"], Decimal("100.00"))

        response = self.client.get(
            "/summary_structure/",
            query_string={"compare_year": 2025, "cluster_id": self.cluster_a},
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="comparison-by-crop"', html)
        self.assertIn('id="comparison-by-company"', html)
        self.assertIn("Порівняння посівних площ: 2026 і 2025", html)
        self.assertIn("Підприємство А", html)
        self.assertNotIn("Підприємство Б", html)
        self.assertIn("Закрити порівняння", html)
        self.assertIn("PDF поточного сезону", html)
        self.assertNotIn('id="global-season-select"', html)
        with self.client.session_transaction() as state:
            self.assertEqual(state["harvest_year"], 2026)

    def test_normal_view_pdf_and_bad_years(self):
        response = self.client.get("/summary_structure/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="open-year-comparison"', html)
        self.assertNotIn('id="comparison-by-crop"', html)
        self.assertIn("Завантажити PDF", html)
        self.assertIn("Структура посівів за культурами", html)
        self.assertIn("175,00", html)
        pdf = self.client.get("/summary_structure/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("zagalna_struktura_2026.pdf",
                      pdf.headers["Content-Disposition"])
        for invalid in ("2026", "2050", "oops", ""):
            self.assertEqual(
                self.client.get("/summary_structure/",
                                query_string={"compare_year": invalid}).status_code,
                400,
                invalid,
            )

    def test_zero_comparison_season_is_not_a_missing_current_year(self):
        result = _comparison_context(self.s26, self.s27, None)
        self.assertEqual(result["overall"]["before"], Decimal("0.00"))
        self.assertEqual(result["overall"]["after"], Decimal("175.00"))
        self.assertIsNone(result["overall"]["percent"])
        response = self.client.get("/summary_structure/",
                                   query_string={"compare_year": 2027})
        self.assertEqual(response.status_code, 200)
        self.assertIn("2026 і 2027", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
