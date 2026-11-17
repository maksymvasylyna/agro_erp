"""One-time 2027 import validation against an isolated disposable database."""
import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ.pop("AGROERP_IMPORT_STRUCTURE_2027_ONCE", None)
os.environ["SECRET_KEY"] = "import-test-only-not-production"

from app import create_app
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldPlanting, FieldSeason, Season
from modules.reference.fields.import_structure_2027 import (
    _source, run_import, OPERATION,
)


class Structure2027ImportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.records = _source()
        cluster = Cluster(name="Кластер для тестів")
        db.session.add(cluster)
        db.session.flush()
        companies = {}
        for name in sorted({r["company"] for r in self.records}):
            company = Company(name=name, cluster_id=cluster.id)
            db.session.add(company)
            db.session.flush()
            companies[name] = company
        cultures = {}
        for name in ["Горох зимуючий"] + sorted({
            r["culture"] for r in self.records if r["culture"] != "Горох озимий"
        }):
            culture = Culture(name=name)
            db.session.add(culture)
            db.session.flush()
            cultures[name] = culture

        # Simulate production: 537 permanent fields exist and ten fields are
        # new; two existing 2027 season allocations are intentionally different
        # from the source and must not be changed.
        for row in self.records[:-10]:
            culture_name = (
                "Горох зимуючий" if row["culture"] == "Горох озимий"
                else row["culture"]
            )
            db.session.add(Field(
                name=row["field"], is_active=True,
                company_id=companies[row["company"]].id,
                cluster_id=cluster.id,
                culture_id=cultures[culture_name].id,
                area=float(row["area"]),
            ))
        db.session.flush()
        season = Season.query.filter_by(year=2027).one()
        self.year_id = season.id
        for number, existing_area, existing_crop in [
            ("МТ0 002", Decimal("34.31"), "Горох зимуючий"),
            ("МТ1 002", Decimal("60.00"), "Кукурудза на силос"),
        ]:
            field = Field.query.filter_by(name=number).one()
            record = FieldSeason(
                season_id=season.id, field_id=field.id,
                company_id=field.company_id, cluster_id=cluster.id,
                area=existing_area,
            )
            db.session.add(record)
            db.session.flush()
            db.session.add(FieldPlanting(
                field_season_id=record.id,
                culture_id=cultures[existing_crop].id, area=existing_area,
            ))
        # A 2026 entry must remain unchanged as well.
        season26 = Season.query.filter_by(year=2026).one()
        field26 = Field.query.filter_by(name="МТ0 002").one()
        rec26 = FieldSeason(
            season_id=season26.id, field_id=field26.id,
            company_id=field26.company_id, cluster_id=cluster.id,
            area=Decimal("77.00"),
        )
        db.session.add(rec26)
        db.session.flush()
        db.session.add(FieldPlanting(
            field_season_id=rec26.id, culture_id=cultures["Соняшник"].id,
            area=Decimal("77.00"),
        ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_full_import_conserves_existing_entries_and_is_idempotent(self):
        result = run_import()
        self.assertEqual(result["new_fields"], 10)
        self.assertEqual(result["new_records"], 545)
        self.assertEqual(result["new_plantings"], 545)
        self.assertEqual(result["matched"], 0)
        self.assertEqual({c["field"] for c in result["conflicts"]},
                         {"МТ0 002", "МТ1 002"})

        records = FieldSeason.query.filter_by(season_id=self.year_id).all()
        self.assertEqual(len(records), 547)
        self.assertEqual(
            sum((item.area for item in records), Decimal("0.00")),
            Decimal("34160.49"),
        )
        self.assertEqual(
            sum((len(item.plantings) for item in records)), 547
        )
        self.assertEqual(Field.query.count(), 547)
        self.assertEqual(
            FieldSeason.query.join(Season).filter(Season.year == 2026).count(),
            1,
        )
        self.assertEqual(
            FieldSeason.query.join(Season).filter(
                Season.year == 2026
            ).first().area, Decimal("77.00"),
        )
        mto = FieldSeason.query.join(Field).filter(
            FieldSeason.season_id == self.year_id,
            Field.name == "МТ0 002",
        ).one()
        self.assertEqual(mto.area, Decimal("34.31"))
        self.assertEqual(mto.plantings[0].culture.name, "Горох зимуючий")
        mti = FieldSeason.query.join(Field).filter(
            FieldSeason.season_id == self.year_id,
            Field.name == "МТ1 002",
        ).one()
        self.assertEqual(mti.area, Decimal("60.00"))
        self.assertEqual(mti.plantings[0].culture.name, "Кукурудза на силос")

        repeated = run_import()
        self.assertEqual(repeated, {"already_imported": True})
        self.assertEqual(FieldSeason.query.filter_by(season_id=self.year_id).count(), 547)
        marker = db.session.execute(db.text(
            "SELECT source_rows, new_fields, conflicting_existing "
            "FROM agroerp_structure_imports WHERE operation_key=:key"
        ), {"key": OPERATION}).one()
        self.assertEqual(tuple(marker), (547, 10, 2))

    def test_source_exact_controls(self):
        self.assertEqual(len(self.records), 547)
        self.assertEqual(
            sum((Decimal(r["area"]) for r in self.records), Decimal("0.00")),
            Decimal("34238.87"),
        )
        self.assertEqual(len({r["field"] for r in self.records}), 547)
        self.assertEqual(len({r["company"] for r in self.records}), 16)


if __name__ == "__main__":
    unittest.main()
