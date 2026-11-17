"""Read-only crop rotation, with Excel-like filters on each year's crop column.

The data source is always FieldSeason and FieldPlanting, not duplicated report
tables. Multi-year visibility is not affected by the global season selector.
"""
import csv
import io
from dataclasses import dataclass, field as model_field
from decimal import Decimal

from flask import Blueprint, Response, jsonify, render_template, request
from sqlalchemy.orm import joinedload, selectinload

from modules.reference.fields.season_models import FieldPlanting, FieldSeason, Season

rotation_bp = Blueprint("rotation", __name__, template_folder="templates")
BLANK = "__empty__"
NONE = "__none__"


@dataclass
class Planting:
    id: int
    name: str
    area: Decimal
    note: str = ""


@dataclass
class SeasonCell:
    area: Decimal
    plantings: list = model_field(default_factory=list)


@dataclass
class RotationRow:
    field_id: int
    field_name: str
    company_name: str
    company_id: int
    latest_year: int = -1
    years: dict = model_field(default_factory=dict)


def _load_rows():
    """Read the complete seasonal history with eager-loaded relations."""
    seasons = Season.query.order_by(Season.year).all()
    if not seasons:
        return [], []
    records = (
        FieldSeason.query.options(
            joinedload(FieldSeason.season),
            joinedload(FieldSeason.field),
            joinedload(FieldSeason.company),
            selectinload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        )
        .filter(FieldSeason.season_id.in_([s.id for s in seasons]))
        .all()
    )
    rows = {}
    for record in records:
        year = record.season.year
        row = rows.get(record.field_id)
        if row is None:
            row = RotationRow(
                field_id=record.field_id, field_name=record.field.name,
                company_name=record.company.name,
                company_id=record.company_id,
            )
            rows[record.field_id] = row
        # Historical enterprise assignments may differ. Use the latest
        # season for the identification columns and preserve all older cells.
        if year > row.latest_year:
            row.company_name = record.company.name
            row.company_id = record.company_id
            row.latest_year = year
        row.years[year] = SeasonCell(
            area=record.area,
            plantings=[
                Planting(p.culture_id, p.culture.name, p.area, p.note or "")
                for p in sorted(record.plantings, key=lambda x: x.culture.name.casefold())
            ],
        )
    result = sorted(rows.values(), key=lambda r: (
        r.company_name.casefold(), r.field_name.casefold(), r.field_id,
    ))
    return [s.year for s in seasons], result


def _cell_values(row, year):
    """One field may have several crops; a missing crop is Excel's blank."""
    cell = row.years.get(year)
    if not cell or not cell.plantings:
        return {BLANK}
    return {str(c.id) for c in cell.plantings}


def _options_for_year(rows, year):
    distinct = {}
    for row in rows:
        cell = row.years.get(year)
        if not cell or not cell.plantings:
            distinct[BLANK] = "(Порожньо)"
        else:
            for crop in cell.plantings:
                distinct[str(crop.id)] = crop.name
    return [
        {"id": key, "name": label}
        for key, label in sorted(
            distinct.items(), key=lambda item: (
                item[0] == BLANK, item[1].casefold()
            )
        )
    ]


def _report_context():
    years, all_rows = _load_rows()
    year_filters = {}
    selected = {}
    active = set()

    for year in years:
        key = f"crop_{year}"
        options = _options_for_year(all_rows, year)
        allowed = {item["id"] for item in options}
        raw = request.args.getlist(key)

        if not raw:
            chosen = allowed.copy()
        elif NONE in raw:
            chosen = set()
        else:
            # Invalid or outdated selections MUST NOT broaden the result.
            chosen = set(raw) & allowed

        if raw and chosen != allowed:
            active.add(year)
        selected[year] = chosen
        year_filters[str(year)] = {
            "options": options,
            "checked": sorted(chosen),
            "active": year in active,
        }

    visible = [
        row for row in all_rows
        if all(_cell_values(row, year) & selected[year] for year in active)
    ]

    totals = {
        year: sum(
            (row.years[year].area for row in visible if year in row.years),
            Decimal("0.00"),
        )
        for year in years
    }
    year_counts = {
        year: sum(year in row.years for row in visible) for year in years
    }
    return {
        "years": years,
        "rows": visible,
        "field_count": len(visible),
        "totals": totals,
        "year_counts": year_counts,
        "year_filters": year_filters,
        "active_years": active,
    }


@rotation_bp.get("/structure/rotation")
def index():
    context = _report_context()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "html": render_template("rotation/_table.html", **context),
            "filters": context["year_filters"],
            "field_count": context["field_count"],
        })
    return render_template("rotation/index.html", **context)


def _safe_csv(value):
    value = str(value)
    # Stop CSV/Excel formula execution from any user-supplied field name.
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _crop_text(cell):
    if not cell:
        return ""
    if len(cell.plantings) == 1 and cell.plantings[0].area == cell.area:
        crop = cell.plantings[0]
        return crop.name + (f" [{crop.note}]" if crop.note else "")
    return " | ".join(
        f"{p.name}: {p.area:.2f} га" + (f" [{p.note}]" if p.note else "")
        for p in cell.plantings
    )


@rotation_bp.get("/structure/rotation/csv")
def export_csv():
    """Download all visible rows, with the very same per-year crop filters."""
    context = _report_context()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")
    header = ["Підприємство", "Номер поля"]
    for year in context["years"]:
        header.extend((f"{year} Площа, га", f"{year} Культура"))
    writer.writerow(header)
    for row in context["rows"]:
        values = [row.company_name, row.field_name]
        for year in context["years"]:
            cell = row.years.get(year)
            values.extend((
                f"{cell.area:.2f}".replace(".", ",") if cell else "",
                _crop_text(cell),
            ))
        writer.writerow([_safe_csv(item) for item in values])
    response = Response(
        "\ufeff" + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                "attachment; filename=agroerp_sivozmina.csv"
        },
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
