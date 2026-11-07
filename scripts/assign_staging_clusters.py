"""One-time assignment of real enterprises to staging clusters.

Mapping is supplied through a private Render environment value; company names
and cluster membership are never committed into the public repository.
"""
import json
import os
from collections import Counter
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import func, text

EXPECTED_YEARS = {2024: 560, 2025: 563, 2026: 550}
EXPECTED_CLUSTER_TOTALS_2026 = {
    "Кластер 1": Decimal("16629.11"),
    "Кластер 2": Decimal("8308.43"),
    "Кластер 3": Decimal("7746.04"),
    "Миколаївське": Decimal("1760.33"),
}


def main():
    raw = os.getenv("AGROERP_CLUSTER_MAP_JSON")
    if not raw:
        return
    uri = os.getenv("RENDER_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if os.getenv("AGROERP_ENV") != "staging" or urlparse(uri).path.rstrip("/") != "/agro_erp_test":
        raise RuntimeError("Cluster assignment allowed only on staging test database.")

    mapping = json.loads(raw)
    if set(mapping) != set(EXPECTED_CLUSTER_TOTALS_2026):
        raise RuntimeError("Unexpected cluster names.")
    if any(not isinstance(v, list) or not v for v in mapping.values()):
        raise RuntimeError("Each cluster must have nonempty company-name list.")

    company_names = [name for names in mapping.values() for name in names]
    if len(company_names) != 16 or len(company_names) != len(set(company_names)):
        raise RuntimeError("Missing or repeated companies in mapping.")

    from app import create_app
    from extensions import db
    from modules.reference.clusters.models import Cluster
    from modules.reference.companies.models import Company
    from modules.reference.fields.field_models import Field
    from modules.structure.seasons.models import FieldSeason, Season

    app = create_app()
    with app.app_context():
        if db.session.execute(text("SELECT current_database()")).scalar_one() != "agro_erp_test":
            raise RuntimeError("DB identity check failed.")
        companies = {x.name: x for x in Company.query.all()}
        if set(companies) != set(company_names):
            raise RuntimeError("Live enterprise list differs from mapping.")

        total_fields = Field.query.count()
        total_rows = FieldSeason.query.count()
        if total_fields != 603 or total_rows != 1673:
            raise RuntimeError("Unexpected number of staging fields or historical records.")

        counts = dict(
            db.session.query(Season.year, func.count(FieldSeason.id))
            .join(FieldSeason, FieldSeason.season_id == Season.id)
            .group_by(Season.year)
            .all()
        )
        if counts != EXPECTED_YEARS:
            raise RuntimeError("Historical record counts differ from source.")

        query = (
            db.session.query(Season.year, Company.name, func.sum(FieldSeason.area))
            .join(FieldSeason, FieldSeason.season_id == Season.id)
            .join(Company, Company.id == FieldSeason.company_id)
            .filter(Season.year == 2026)
            .group_by(Season.year, Company.name)
        )
        company_hectares = {name: Decimal(area) for _, name, area in query.all()}
        for cluster, members in mapping.items():
            total = sum((company_hectares.get(name, Decimal(0)) for name in members), Decimal(0))
            if total != EXPECTED_CLUSTER_TOTALS_2026[cluster]:
                raise RuntimeError(f"Cluster checksum mismatch: {cluster} ({total})")

        existing_clusters = {c.name: c for c in Cluster.query.all()}
        if set(existing_clusters) == set(EXPECTED_CLUSTER_TOTALS_2026):
            for cluster, names in mapping.items():
                cluster_id = existing_clusters[cluster].id
                if any(companies[name].cluster_id != cluster_id for name in names):
                    raise RuntimeError("Existing mapping mismatch. Manual review required.")
            print("Staging clusters already assigned; skipped.")
            return

        if set(existing_clusters) != {"Без кластеризації (історичне джерело)"}:
            raise RuntimeError("Unexpected clusters: refusing to remap.")

        for name in mapping:
            db.session.add(Cluster(name=name))
        db.session.flush()
        new_clusters = {c.name: c for c in Cluster.query.all()}
        for cluster, names in mapping.items():
            target_cluster_id = new_clusters[cluster].id
            for company_name in names:
                company = companies[company_name]
                company.cluster_id = target_cluster_id
                Field.query.filter_by(company_id=company.id).update(
                    {Field.cluster_id: target_cluster_id}, synchronize_session=False
                )
                FieldSeason.query.filter_by(company_id=company.id).update(
                    {FieldSeason.cluster_id: target_cluster_id}, synchronize_session=False
                )

        db.session.flush()
        old_cluster = existing_clusters["Без кластеризації (історичне джерело)"]
        db.session.delete(old_cluster)
        db.session.commit()
        print("Assigned 16 companies and 603 fields to 4 sourced cluster groups.")


if __name__ == "__main__":
    main()
