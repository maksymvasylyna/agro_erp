"""Season-aware field planting table with independent checkbox multi-filters."""
from decimal import Decimal

from flask import Blueprint, render_template, request, session
from sqlalchemy import false

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.structure.seasons.models import FieldPlanting, FieldSeason, Season

fields_structure_bp = Blueprint("fields_structure", __name__, template_folder="templates")

FILTER_KEYS = ("clusters", "companies", "cultures")


def _selection(key, available_ids):
    """No query parameter means all; an explicit '__none__' means no matches.

    Unknown identifiers never broaden a filter. Each dimension uses OR across
    checked values, while different dimensions combine with AND.
    """
    raw = request.args.getlist(key)
    available = set(available_ids)
    if not raw:
        return None, available
    if "__none__" in raw:
        return [], set()
    selected = set()
    for value in raw:
        try:
            choice = int(value)
        except (ValueError, TypeError):
            continue
        if choice in available:
            selected.add(choice)
    return sorted(selected), selected


@fields_structure_bp.route("/structure/fields", methods=["GET"])
def index():
    year = session.get("harvest_year")
    season = Season.query.filter_by(year=year).first() if year else None
    if season is None:
        season = Season.query.order_by(Season.year.desc()).first()
    if season is not None:
        session["harvest_year"] = season.year

    cluster_options = []
    company_options = []
    culture_options = []
    rows = []

    if season:
        cluster_ids = [
            x[0] for x in db.session.query(FieldSeason.cluster_id)
            .filter(FieldSeason.season_id == season.id).distinct()
        ]
        company_ids = [
            x[0] for x in db.session.query(FieldSeason.company_id)
            .filter(FieldSeason.season_id == season.id).distinct()
        ]
        culture_ids = [
            x[0] for x in db.session.query(FieldPlanting.culture_id)
            .join(FieldSeason, FieldSeason.id == FieldPlanting.field_season_id)
            .filter(FieldSeason.season_id == season.id).distinct()
        ]

        cluster_options = (
            Cluster.query.filter(Cluster.id.in_(cluster_ids))
            .order_by(Cluster.name).all()
        )
        company_options = (
            Company.query.filter(Company.id.in_(company_ids))
            .order_by(Company.name).all()
        )
        culture_options = (
            Culture.query.filter(Culture.id.in_(culture_ids))
            .order_by(Culture.name).all()
        )

    options = {
        "clusters": cluster_options,
        "companies": company_options,
        "cultures": culture_options,
    }
    filters = {}
    checked = {}
    for key in FILTER_KEYS:
        filters[key], checked[key] = _selection(key, [obj.id for obj in options[key]])

    if season:
        query = (
            FieldPlanting.query.join(FieldSeason)
            .filter(FieldSeason.season_id == season.id)
        )
        if filters["clusters"] is not None:
            query = query.filter(
                FieldSeason.cluster_id.in_(filters["clusters"])
                if filters["clusters"] else false()
            )
        if filters["companies"] is not None:
            query = query.filter(
                FieldSeason.company_id.in_(filters["companies"])
                if filters["companies"] else false()
            )
        if filters["cultures"] is not None:
            query = query.filter(
                FieldPlanting.culture_id.in_(filters["cultures"])
                if filters["cultures"] else false()
            )
        rows = query.order_by(
            FieldSeason.company_id, FieldSeason.field_id, FieldPlanting.culture_id
        ).all()

    total_area = sum((row.area for row in rows), Decimal("0.00"))
    context = dict(items=rows, total_area=total_area, count=len(rows), season=season)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Table only: the checkbox popovers stay open during auto-updates.
        return render_template("fields_structure/_results.html", **context)

    return render_template(
        "fields_structure/index.html",
        **context, options=options, checked=checked,
    )
