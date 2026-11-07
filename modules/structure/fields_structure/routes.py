"""Season-aware detailed crop structure."""
from decimal import Decimal

from flask import Blueprint, render_template, request, session

from modules.reference.cultures.models import Culture
from modules.structure.fields_structure.forms import FieldsStructureFilterForm
from modules.structure.seasons.models import FieldPlanting, FieldSeason, Season

fields_structure_bp = Blueprint("fields_structure", __name__, template_folder="templates")


@fields_structure_bp.route("/structure/fields")
def index():
    filter_form = FieldsStructureFilterForm(request.args)
    year = session.get("harvest_year")
    season = Season.query.filter_by(year=year).first() if year else None
    if season is None:
        season = Season.query.order_by(Season.year.desc()).first()

    rows = []
    if season:
        query = (
            FieldPlanting.query.join(FieldSeason)
            .filter(FieldSeason.season_id == season.id)
        )
        if filter_form.cluster.data:
            query = query.filter(FieldSeason.cluster_id == filter_form.cluster.data.id)
        if filter_form.company.data:
            query = query.filter(FieldSeason.company_id == filter_form.company.data.id)
        if filter_form.culture.data:
            query = query.filter(FieldPlanting.culture_id == filter_form.culture.data.id)
        rows = query.order_by(FieldSeason.company_id, FieldSeason.field_id).all()

    total_area = sum((row.area for row in rows), Decimal("0.00"))
    return render_template(
        "fields_structure/index.html", filter_form=filter_form,
        items=rows, total_area=total_area, season=season,
    )
