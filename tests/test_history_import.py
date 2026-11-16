"""Import tests: disposable SQLite, no connected production PostgreSQL."""
import json
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ.pop("AGROERP_FIELD_HISTORY_IMPORT", None)
os.environ["SECRET_KEY"] = "tests-only-not-production-key-history"

from app import create_app
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting
from scripts.import_field_history_2020_2026 import import_history_text, _checksum


class HistoryImportTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        cl = Cluster(name="Кластер 1")
        db.session.add(cl)
        db.session.flush()
        self.company = Company(name="Агроконтракт-Н 2021 ТОВ", cluster_id=cl.id)
        self.second = Company(name="Тясмин СТОВ", cluster_id=cl.id)
        db.session.add_all([self.company, self.second])
        db.session.add_all([
            Culture(name="Пшениця озима"), Culture(name="Соняшник"),
            Culture(name="Кукурудза на зерно")
        ])
        # The production reference sync has already introduced 2020-2025.
        db.session.add(Season(year=2020))
        db.session.commit()

        # Existing active field and a legacy 2026 rotation that must be
        # reconciled against the source. 2027 must never be modified.
        self.old_field = Field(
            name="АКП 001", company_id=self.company.id,
            cluster_id=cl.id, area=999.0,
            culture_id=Culture.query.filter_by(name="Пшениця озима").one().id,
            is_active=True,
        )
        self.stale_field = Field(
            name="OLD 999", company_id=self.company.id,
            cluster_id=cl.id, area=22.0,
            culture_id=Culture.query.filter_by(name="Соняшник").one().id,
            is_active=True,
        )
        db.session.add_all([self.old_field, self.stale_field])
        db.session.flush()
        y2026 = Season.query.filter_by(year=2026).one()
        y2027 = Season.query.filter_by(year=2027).one()
        historical = FieldSeason(
            season_id=y2026.id, field_id=self.old_field.id,
            company_id=self.company.id, cluster_id=cl.id, area=99.0,
        )
        stale = FieldSeason(
            season_id=y2026.id, field_id=self.stale_field.id,
            company_id=self.company.id, cluster_id=cl.id, area=22.0,
        )
        future = FieldSeason(
            season_id=y2027.id, field_id=self.old_field.id,
            company_id=self.company.id, cluster_id=cl.id, area=60.0,
        )
        db.session.add_all([historical, stale, future])
        db.session.flush()
        crop_id = Culture.query.filter_by(name="Соняшник").one().id
        db.session.add_all([
            FieldPlanting(field_season_id=historical.id, culture_id=crop_id, area=99),
            FieldPlanting(field_season_id=stale.id, culture_id=crop_id, area=22),
            FieldPlanting(field_season_id=future.id, culture_id=crop_id, area=60)
        ])
        db.session.commit()
        self.old_id = self.old_field.id
        self.future_id = future.id
        self.payload = {
            "v": 1,
            "organizations": ["Агроконтракт-Н 2021 ТОВ", "Тясмин СТОВ"],
            "crops": ["Кукурудза", "Соняшник сторонній", "Пшениця озима"],
            "fields": [
                [0, "АКП 001", [[2020, 12550, 0], [2026, 11020, 2]]],
                [1, "ТС 002", [[2020, 2222, 1]]],
            ],
            "stats": {"2020": [2, 14772], "2026": [1, 11020]},
        }
        self.settings = {
            "expected_stats": {2020: (2, 14772), 2026: (1, 11020)},
            "expected_fields": 2,
            "expected_organizations": 2,
        }

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.execute(db.text("DROP TABLE IF EXISTS agroerp_history_import_state"))
        db.session.commit()
        self.ctx.pop()

    def _import(self, payload=None, checksum=None):
        raw = json.dumps(payload or self.payload, ensure_ascii=False, separators=(",", ":"))
        return import_history_text(raw, source_checksum=checksum, **self.settings)

    def test_merge_existing_id_and_keep_future_intact(self):
        out = self._import()
        self.assertFalse(out["skipped"])
        self.assertEqual(out["created_fields"], 1)
        self.assertEqual(out["plantings"], 3)
        self.assertEqual(out["removed_legacy_seasonal"], 1)
        self.assertEqual(db.session.get(Field, self.old_id).area, 999.0)
        self.assertEqual(db.session.get(FieldSeason, self.future_id).area, 60)
        self.assertEqual(Season.query.filter_by(year=2027).one().fields[0].id, self.future_id)
        self.assertEqual(FieldSeason.query.count(), 4)
        self.assertEqual(FieldPlanting.query.count(), 4)

        historical = FieldSeason.query.join(Season).filter(
            FieldSeason.field_id == self.old_id, Season.year == 2026
        ).one()
        self.assertEqual(historical.area, Decimal("110.20"))
        self.assertEqual(len(historical.plantings), 1)
        # The original 2026 planting (99 ha sunflower) must be replaced.
        self.assertEqual(historical.plantings[0].culture.name, "Пшениця озима")
        external = FieldPlanting.query.filter(
            FieldPlanting.note == "Джерело: Соняшник сторонній"
        ).one()
        self.assertEqual(external.culture.name, "Соняшник")
        self.assertEqual(external.area, Decimal("22.22"))
        again = self._import()
        self.assertTrue(again["skipped"])
        self.assertEqual(FieldSeason.query.count(), 4)

    def test_corrupt_checksum_fails_without_writes(self):
        with self.assertRaisesRegex(ValueError, "цілісності"):
            self._import(checksum="ffffffff")
        self.assertEqual(FieldSeason.query.count(), 3)

    def test_duplicate_or_inconsistent_source_refused(self):
        bad = json.loads(json.dumps(self.payload))
        bad["fields"].append(bad["fields"][0])
        with self.assertRaisesRegex(ValueError, "кількість фізичних"):
            self._import(bad)
        self.assertEqual(FieldSeason.query.count(), 3)

    def test_check_monthly_data_stable(self):
        raw = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))
        result = import_history_text(raw, source_checksum=_checksum(raw), **self.settings)
        self.assertEqual(result["plantings"], 3)


if __name__ == "__main__":
    unittest.main()
