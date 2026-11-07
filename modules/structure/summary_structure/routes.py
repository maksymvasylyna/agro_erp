"""Crop-area summary for one selected harvest season.

Rows are enterprises, columns are crops. Switching the global harvest year
changes the query but preserves the current report and cluster filter.
"""
from collections import defaultdict
from decimal import Decimal

from flask import Blueprint, render_template, request, session
from sqlalchemy import func

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.structure.seasons.models import FieldPlanting, FieldSeason, Season

bp = Blueprint(
    "summary_structure", __name__, url_prefix="/summary_structure",
    template_folder="templates",
)

ZERO = Decimal("0.00")


@bp.app_template_filter("ua_area")
def ua_area(value):
    """Format hectares to two decimals using Ukrainian separators."""
    return f"{Decimal(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


@bp.route("/", methods=["GET"])
def index():
    selected_year = session.get("harvest_year")
    season = Season.query.filter_by(year=selected_year).first() if selected_year else None
    if season is None:
        season = Season.query.order_by(Season.year.desc()).first()
    if season:
        session["harvest_year"] = season.year

    cluster_options = Cluster.query.order_by(Cluster.name).all()
    selected_cluster = request.args.get("cluster_id", type=int)
    if selected_cluster not in {cluster.id for cluster in cluster_options}:
        selected_cluster = None

    matrix = {}
    crops = []
    cluster_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    grand_totals = defaultdict(lambda: ZERO)

    if season:
        # Sum only crop allocations in the selected year; a multi-crop field
        # contributes once to each culture's allocated area, not its full area.
        query = (
            db.session.query(
                Cluster.name.label("cluster"),
                Company.name.label("company"),
                Culture.name.label("culture"),
                func.sum(FieldPlanting.area).label("area"),
            )
            .select_from(FieldPlanting)
            .join(FieldSeason, FieldSeason.id == FieldPlanting.field_season_id)
            .join(Cluster, Cluster.id == FieldSeason.cluster_id)
            .join(Company, Company.id == FieldSeason.company_id)
            .join(Culture, Culture.id == FieldPlanting.culture_id)
            .filter(FieldSeason.season_id == season.id)
        )
        if selected_cluster is not None:
            query = query.filter(FieldSeason.cluster_id == selected_cluster)
        rows = (
            query.group_by(Cluster.name, Company.name, Culture.name)
            .order_by(Cluster.name, Company.name, Culture.name)
            .all()
        )
        crops = sorted({row.culture for row in rows})
        for row in rows:
            allocation = Decimal(row.area)
            matrix.setdefault(row.cluster, {}).setdefault(row.company, {})[row.culture] = allocation
            cluster_totals[row.cluster][row.culture] += allocation
            grand_totals[row.culture] += allocation

    return render_template(
        "summary_structure/index.html",
        season=season,
        matrix=matrix,
        crops=crops,
        cluster_totals=cluster_totals,
        grand_totals=grand_totals,
        cluster_options=cluster_options,
        selected_cluster=selected_cluster,
    )
