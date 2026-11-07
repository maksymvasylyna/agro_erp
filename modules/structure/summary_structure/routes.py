"""Harvest-year aware summary of planted hectares."""
from collections import defaultdict
from decimal import Decimal

from flask import Blueprint, render_template, request, session
from sqlalchemy import func

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.structure.seasons.models import FieldPlanting, FieldSeason, Season

bp = Blueprint("summary_structure", __name__, url_prefix="/summary_structure", template_folder="templates")


@bp.route("/", methods=["GET"])
def index():
    year = session.get("harvest_year")
    season = Season.query.filter_by(year=year).first() if year else None
    if season is None:
        season = Season.query.order_by(Season.year.desc()).first()

    cluster_id = request.args.get("cluster_id", type=int)
    clusters_filter = Cluster.query.order_by(Cluster.name).all()
    rows = []
    if season:
        query = (
            db.session.query(
                Cluster.name.label("cluster"), Company.name.label("company"),
                Culture.name.label("culture"),
                func.sum(FieldPlanting.area).label("total_area"),
            )
            .select_from(FieldPlanting)
            .join(FieldSeason, FieldPlanting.field_season_id == FieldSeason.id)
            .join(Cluster, FieldSeason.cluster_id == Cluster.id)
            .join(Company, FieldSeason.company_id == Company.id)
            .join(Culture, FieldPlanting.culture_id == Culture.id)
            .filter(FieldSeason.season_id == season.id)
        )
        if cluster_id:
            query = query.filter(FieldSeason.cluster_id == cluster_id)
        rows = query.group_by(Cluster.name, Company.name, Culture.name).order_by(
            Cluster.name, Company.name, Culture.name
        ).all()

    result = {}
    cultures = sorted({r.culture for r in rows})
    clusters = sorted({r.cluster for r in rows})
    cluster_totals = defaultdict(lambda: defaultdict(Decimal))
    company_totals = defaultdict(dict)
    total_row = defaultdict(Decimal)
    for r in rows:
        result.setdefault(r.cluster, {}).setdefault(r.company, {})[r.culture] = r.total_area
        cluster_totals[r.cluster][r.culture] += r.total_area
        total_row[r.culture] += r.total_area
    for cluster in clusters:
        for company, culture_areas in result[cluster].items():
            company_totals[cluster][company] = sum(culture_areas.values(), Decimal("0.00"))
        cluster_totals[cluster]["Разом"] = sum(
            (cluster_totals[cluster][culture] for culture in cultures), Decimal("0.00")
        )
    total_row["Разом"] = sum((total_row[c] for c in cultures), Decimal("0.00"))

    return render_template(
        "summary_structure/index.html", result=result, seasons=None, season=season,
        clusters=clusters, cultures=cultures, cluster_totals=cluster_totals,
        company_totals=company_totals, total_row=total_row,
        clusters_filter=clusters_filter, selected_cluster=cluster_id,
    )
