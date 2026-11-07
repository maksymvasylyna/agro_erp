"""Season-aware field structure with hierarchical, multi-select column filters.

Facet order: cluster -> company -> crop -> field number -> planting area.
Multiple choices within a facet are OR-ed, and separate facets are AND-ed.
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, jsonify, render_template, request, session
from sqlalchemy.orm import joinedload

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.structure.seasons.models import FieldPlanting, FieldSeason, Season

fields_structure_bp = Blueprint("fields_structure", __name__, template_folder="templates")

FILTER_KEYS = ("clusters", "companies", "cultures", "fields")


def _selection(key, available_ids):
    """Return canonical selected IDs and set of matching values.

    No parameter means 'all'; '__none__' means an explicit empty selection.
    Stale or malformed IDs never cause a broader-than-requested result.
    """
    raw = request.args.getlist(key)
    available = set(available_ids)
    if not raw:
        return sorted(available), available
    if "__none__" in raw:
        return [], set()

    selected = set()
    for value in raw:
        try:
            parsed = int(value)
        except (ValueError, TypeError):
            continue
        if parsed in available:
            selected.add(parsed)
    return sorted(selected), selected


def _area_value(key):
    raw = request.args.get(key, "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        abort(400, description="Некоректне значення площі.")
    if not value.is_finite() or value < 0:
        abort(400, description="Площа має бути невід'ємним числом.")
    return value


def _options(ids, model):
    if not ids:
        return []
    return model.query.filter(model.id.in_(ids)).order_by(model.name).all()


@fields_structure_bp.route("/structure/fields", methods=["GET"])
def index():
    year = session.get("harvest_year")
    season = Season.query.filter_by(year=year).first() if year else None
    if season is None:
        season = Season.query.order_by(Season.year.desc()).first()
    if season is not None:
        session["harvest_year"] = season.year

    all_rows = []
    if season:
        all_rows = (
            FieldPlanting.query.join(FieldSeason)
            .options(
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.field),
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.cluster),
                joinedload(FieldPlanting.field_season).joinedload(FieldSeason.company),
                joinedload(FieldPlanting.culture),
            )
            .filter(FieldSeason.season_id == season.id)
            .all()
        )

    # Each next list is built from rows matching the preceding filters.
    cluster_ids = {p.field_season.cluster_id for p in all_rows}
    clusters_selected, cluster_set = _selection("clusters", cluster_ids)
    in_clusters = [p for p in all_rows if p.field_season.cluster_id in cluster_set]

    company_ids = {p.field_season.company_id for p in in_clusters}
    companies_selected, company_set = _selection("companies", company_ids)
    in_companies = [
        p for p in in_clusters if p.field_season.company_id in company_set
    ]

    culture_ids = {p.culture_id for p in in_companies}
    cultures_selected, culture_set = _selection("cultures", culture_ids)
    in_cultures = [p for p in in_companies if p.culture_id in culture_set]

    field_ids = {p.field_season.field_id for p in in_cultures}
    fields_selected, field_set = _selection("fields", field_ids)
    in_fields = [p for p in in_cultures if p.field_season.field_id in field_set]

    area_min = _area_value("area_min")
    area_max = _area_value("area_max")
    rows = [
        p for p in in_fields
        if (area_min is None or p.area >= area_min)
        and (area_max is None or p.area <= area_max)
    ]
    rows.sort(key=lambda p: (
        p.field_season.cluster.name.casefold(),
        p.field_season.company.name.casefold(),
        p.field_season.field.name.casefold(),
        p.culture.name.casefold(),
    ))

    options = {
        "clusters": _options(cluster_ids, Cluster),
        "companies": _options(company_ids, Company),
        "cultures": _options(culture_ids, Culture),
        "fields": _options(field_ids, Field),
    }
    checked = {
        "clusters": clusters_selected,
        "companies": companies_selected,
        "cultures": cultures_selected,
        "fields": fields_selected,
    }
    total_area = sum((p.area for p in rows), Decimal("0.00"))
    context = dict(
        items=rows, total_area=total_area, count=len(rows), season=season,
        options=options, checked=checked,
        area_min=area_min, area_max=area_max,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        html = render_template("fields_structure/_results.html", **context)
        if request.accept_mimetypes.best == "application/json":
            return jsonify({
                "html": html,
                "options": {
                    key: [{"id": item.id, "name": item.name} for item in entries]
                    for key, entries in options.items()
                },
                "checked": checked,
            })
        return html

    return render_template("fields_structure/index.html", **context)
