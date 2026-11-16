"""Read/write tests for the one-time historical reference sync (SQLite only)."""
import os
import unittest
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-secret-key-for-dictionary-sync-only-2026"
os.environ.pop("AGROERP_SYNC_FIELD_REFS_2020_2026", None)

from app import create_app
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season
from scripts.sync_field_history_references import (
    COMPANIES, MISSING_CULTURES, MISSING_YEARS,
    build_reference_plan, sync_reference_dictionaries,
)


class HistoricalReferencesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        clusters = [Cluster(name=n) for n in (
            "Кластер 1", "Кластер 2", "Кластер 3", "ТОВ ПрАТ Миколаївське"
        )]
        db.session.add_all(clusters)
        db.session.flush()
        self.original_company = Company(name="ТОВ Агроконтракт", cluster_id=clusters[0].id)
        db.session.add(self.original_company)
        self.original_crop = Culture(name="Кукурудза на зерно")
        db.session.add(self.original_crop)
        db.session.flush()
        self.field = Field(name="АКП 001", cluster_id=clusters[0].id,
                           company_id=self.original_company.id,
                           culture_id=self.original_crop.id, area=50.0)
        db.session.add(self.field)
        db.session.commit()
        self.company_id = self.original_company.id
        self.field_id = self.field.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_preflight_does_not_touch_database(self):
        plan = build_reference_plan()
        self.assertEqual(len(plan["company_additions"]), 16)
        self.assertEqual(len(plan["company_renames"]), 1)
        report = sync_reference_dictionaries(dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(Company.query.count(), 1)
        self.assertEqual(Culture.query.count(), 1)
        self.assertEqual(Season.query.count(), 2)
        self.assertEqual(Cluster.query.filter_by(name="ТОВ ПрАТ Миколаївське").count(), 1)

    def test_apply_preserves_ids_and_is_idempotent(self):
        result = sync_reference_dictionaries(dry_run=False)
        self.assertFalse(result["dry_run"])
        self.assertEqual(Company.query.count(), len(COMPANIES))
        self.assertEqual(Culture.query.count(), 1 + len(MISSING_CULTURES))
        self.assertEqual(set(MISSING_YEARS).issubset({s.year for s in Season.query.all()}), True)
        self.assertEqual(len(Season.query.all()), 8)
        self.assertEqual(Cluster.query.count(), 4)
        self.assertIsNotNone(Cluster.query.filter_by(name="Миколаївське").one_or_none())
        preserved = db.session.get(Field, self.field_id)
        self.assertEqual(preserved.company_id, self.company_id)
        self.assertEqual(preserved.culture_id, self.original_crop.id)
        self.assertEqual(db.session.get(Company, self.company_id).name, "Агроконтракт-Н 2021 ТОВ")
        self.assertTrue(Company.query.filter_by(name="Агроконтракт-Н(проект) ТОВ").first())

        again = sync_reference_dictionaries(dry_run=False)
        for key in ("company_renames", "company_additions", "culture_additions",
                    "cluster_renames", "season_additions"):
            self.assertEqual(again[key], [], key)
        self.assertEqual(Company.query.count(), len(COMPANIES))

    def test_wrong_cluster_aborts_without_changes(self):
        another = Company(name="ТОВ Горизонт", cluster_id=Cluster.query.filter_by(name="Кластер 2").one().id)
        db.session.add(another)
        db.session.commit()
        with self.assertRaisesRegex(ValueError, "Невідповідний кластер"):
            sync_reference_dictionaries(dry_run=False)
        self.assertEqual(Company.query.count(), 2)
        self.assertEqual(Culture.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
