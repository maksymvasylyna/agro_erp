"""Non-mutating smoke tests for the separate Render old-planning demo."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.plans.models import Plan
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company


def check():
    app = create_app()
    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            raise RuntimeError("Preview check cannot run against PostgreSQL.")
        season = Season.query.filter_by(year=2027).one()
        assert not season.is_closed
        cluster = Cluster.query.filter_by(name="DEMO Північний кластер").one()
        company = Company.query.filter_by(name="DEMO Господарство Північ").one()
        unplanned = Field.query.filter_by(name="DEMO-101").one()
        ready = Field.query.filter_by(name="DEMO-103").one()
        approved = Field.query.filter_by(name="DEMO-201").one()
        assert Plan.query.filter_by(field_id=unplanned.id, season_id=season.id).count() == 0
        assert Plan.query.filter_by(field_id=ready.id, is_approved=False, season_id=season.id).count() == 1
        assert Plan.query.filter_by(field_id=approved.id, is_approved=True, season_id=season.id).count() == 1

        client = app.test_client()
        switched = client.get("/fields/select-season",
                              query_string={"year": 2027, "next": "/plans/"})
        assert switched.status_code == 302, switched.status_code
        urls = [
            ("/", "Agro"),
            ("/plans/", "Нові плани"),
            ("/new_plans/", "Створити план по полю"),
            ("/new_plans/select_cluster", "DEMO Північний кластер"),
            (f"/new_plans/select_company/{cluster.id}", company.name),
            (f"/new_plans/select_field/{cluster.id}/{company.id}", "DEMO-101"),
            (f"/new_plans/create/{unplanned.id}", "DEMO-101"),
            ("/plans/ready/", "DEMO-103"),
            ("/approved_plans/", "DEMO-201"),
        ]
        for path, marker in urls:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            assert marker in response.get_data(as_text=True), (path, marker)
            print(f"OK HTTP 200 {path}")
        ready_plan = Plan.query.filter_by(field_id=ready.id).one()
        approved_plan = Plan.query.filter_by(field_id=approved.id).one()
        for path in (
            f"/plans/ready/approve_plan/{ready_plan.id}",
            f"/approved_plans/unlock/{approved_plan.id}",
        ):
            response = client.get(path)
            assert response.status_code == 405, (path, response.status_code)
            print(f"OK GET rejected 405 {path}")
        # Unauthenticated + untrusted forms never approve or unlock plans.
        response = client.post(f"/plans/ready/approve_plan/{ready_plan.id}",
                               data={"season_id": str(season.id)})
        assert response.status_code in (400, 403), response.status_code
        assert not db.session.get(Plan, ready_plan.id).is_approved
    print("All isolated old-planning preview checks passed.")


if __name__ == "__main__":
    check()
