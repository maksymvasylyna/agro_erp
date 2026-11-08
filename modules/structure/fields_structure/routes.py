"""Season-specific, read-only field-area structure.

Physical field area is counted exactly once per seasonal field, even when
multiple crop plantings occupy the same physical field.
"""
from decimal import Decimal

from flask import Blueprint, render_template, request
from sqlalchemy.orm import joinedload, selectinload

from modules.reference.fields.field_models import Field
from modules.reference.fields.forms import FieldFilterForm
from modules.reference.fields.routes import _view_context
from modules.reference.fields.season_models import FieldPlanting, FieldSeason

fields_structure_bp = Blueprint(
    "fields_structure", __name__, template_folder="templates"
)


@fields_structure_bp.route("/structure/fields")
def index():
    ctx = _view_context()  # Same session-selected harvest year as the Fields directory.
    season = ctx["season"]
    filter_form = FieldFilterForm(request.args)
    culture_id = filter_form.culture.data.id if filter_form.culture.data else None

    items = []
    total_area = Decimal("0.00")
    total_planted = Decimal("0.00")
    total_unallocated = Decimal("0.00")

    if season is not None:
        query = (
            FieldSeason.query
            .join(Field, FieldSeason.field_id == Field.id)
            .options(
                joinedload(FieldSeason.field),
                joinedload(FieldSeason.cluster),
                joinedload(FieldSeason.company),
                selectinload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
            )
            .filter(FieldSeason.season_id == season.id)
        )
        if filter_form.cluster.data:
            query = query.filter(FieldSeason.cluster_id == filter_form.cluster.data.id)
        if filter_form.company.data:
            query = query.filter(FieldSeason.company_id == filter_form.company.data.id)
        if culture_id is not None:
            query = query.filter(
                FieldSeason.plantings.any(FieldPlanting.culture_id == culture_id)
            )

        for field_season in query.order_by(
            FieldSeason.cluster_id, FieldSeason.company_id, Field.name
        ).all():
            visible_plantings = [
                planting for planting in field_season.plantings
                if culture_id is None or planting.culture_id == culture_id
            ]
            visible_planted = sum(
                (planting.area for planting in visible_plantings), Decimal("0.00")
            )
            items.append({
                "field_season": field_season,
                "plantings": visible_plantings,
                "visible_planted": visible_planted,
            })
            # Never sum the physical field area separately for each crop.
            total_area += field_season.area
            total_planted += visible_planted
            total_unallocated += field_season.unallocated_area

    return render_template(
        "fields_structure/index.html",
        **ctx,
        filter_form=filter_form,
        items=items,
        total_area=total_area,
        total_planted=total_planted,
        total_unallocated=total_unallocated,
        culture_filtered=culture_id is not None,
    )
