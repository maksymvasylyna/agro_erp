"""Season-aware summary: companies as rows, harvest years as columns.

Matches the layout of the source workbook's 'Зведена площа' sheet.
Crop composition for the selected year is a separate optional detail table.
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
    """Format hectares to two decimals with Ukrainian separators."""
    return f"{Decimal(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


@bp.route("/", methods=["GET"])
def index():
    seasons = Season.query.order_by(Season.year.asc()).all()
    years = [s.year for s in seasons]
    selected_year = session.get("harvest_year")
    season = next((s for s in seasons if s.year == selected_year), None)
    if season is None and seasons:
        season = seasons[-1]
    if season is not None:
        session["harvest_year"] = season.year

    selected_cluster = request.args.get("cluster_id", type=int)
    cluster_options = Cluster.query.order_by(Cluster.name).all()
    if selected_cluster not in {c.id for c in cluster_options}:
        selected_cluster = None

    # Use FieldSeason, not FieldPlanting, for the physical land-bank area.
    # Otherwise splitting one field into two crops could double-count it.
    area_query = (
        db.session.query(
            Cluster.id.label("cluster_id"),
            Cluster.name.label("cluster"),
            Company.id.label("company_id"),
            Company.name.label("company"),
            Season.year.label("year"),
            func.sum(FieldSeason.area).label("area"),
        )
        .select_from(FieldSeason)
        .join(Season, Season.id == FieldSeason.season_id)
        .join(Company, Company.id == FieldSeason.company_id)
        .join(Cluster, Cluster.id == FieldSeason.cluster_id)
    )
    if selected_cluster is not None:
        area_query = area_query.filter(FieldSeason.cluster_id == selected_cluster)
    area_rows = (
        area_query.group_by(
            Cluster.id, Cluster.name, Company.id, Company.name, Season.year,
        )
        .order_by(Cluster.name, Company.name, Season.year)
        .all()
    )

    matrix = {}
    cluster_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    year_totals = defaultdict(lambda: ZERO)
    for r in area_rows:
        group = matrix.setdefault(r.cluster, {})
        company = group.setdefault(r.company, {year: ZERO for year in years})
        value = Decimal(r.area)
        company[r.year] = value
        cluster_totals[r.cluster][r.year] += value
        year_totals[r.year] += value

    # Detailed crop allocations for selected season, kept independent of the
    # yearly enterprise-area summary above.
    crop_matrix = {}
    crops = []
    crop_cluster_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    crop_year_totals = defaultdict(lambda: ZERO)
    if season:
        crop_query = (
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
            crop_query = crop_query.filter(FieldSeason.cluster_id == selected_cluster)
        crop_rows = (
            crop_query.group_by(Cluster.name, Company.name, Culture.name)
            .order_by(Cluster.name, Company.name, Culture.name)
            .all()
        )
        crops = sorted({r.culture for r in crop_rows})
        for r in crop_rows:
            group = crop_matrix.setdefault(r.cluster, {})
            company = group.setdefault(r.company, {})
            value = Decimal(r.area)
            company[r.culture] = value
            crop_cluster_totals[r.cluster][r.culture] += value
            crop_year_totals[r.culture] += value

    return render_template(
        "summary_structure/index.html",
        years=years, season=season, matrix=matrix,
        clusters=list(matrix.keys()), cluster_totals=cluster_totals,
        year_totals=year_totals, selected_cluster=selected_cluster,
        cluster_options=cluster_options, crop_matrix=crop_matrix,
        crops=crops, crop_cluster_totals=crop_cluster_totals,
        crop_year_totals=crop_year_totals,
    )
