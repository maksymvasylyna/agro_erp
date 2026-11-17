"""Read-only, multi-year crop-rotation report.

All values are read from Field/Season/FieldSeason/FieldPlanting dictionaries.
No year writes, copies, updates or destructive actions are exposed here.
"""
import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, abort, jsonify, render_template, request
from sqlalchemy.orm import joinedload, selectinload

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.season_models import FieldPlanting, FieldSeason, Season

rotation_bp = Blueprint("rotation", __name__, template_folder="templates")

FACETS = ("clusters", "companies", "masses", "cultures")


@dataclass
class CropCell:
    name: str
    area: Decimal
    note: str = ""


@dataclass
class YearCell:
    area: Decimal
    crops: list = dataclass_field(default_factory=list)


@dataclass
class ReportRow:
    id: int
    name: str
    cluster_id: int
    cluster: str
    company_id: int
    company: str
    mass: str
    years: dict = dataclass_field(default_factory=dict)
    latest_year: int = -1
    field_count: int = 1


def _mass_prefix(field_name):
    """Provisional field-array label from the source field-number prefix.

    This is NOT a separate spatial/official mass identity. Only group fields
    sharing the prefix AND the same company+cluster.
    """
    name = " ".join((field_name or "").strip().split())
    parts = name.split(" ", 1)
    if len(parts) > 1:
        return parts[0].upper()
    match = re.match(r"[^0-9/]+", name)
    return match.group(0).strip().upper() if match and match.group(0).strip() else name.upper()


def _year_param(key, years, default):
    raw = request.args.get(key, "")
    if not raw:
        return default
    try:
        year = int(raw)
    except ValueError:
        abort(400, description="Некоректне значення року.")
    if year not in years:
        abort(400, description="Рік відсутній у довіднику сезонів.")
    return year


def _area_param(key):
    raw = (request.args.get(key) or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        abort(400, description="Некоректна площа.")
    if not value.is_finite() or value < 0:
        abort(400, description="Площа повинна бути невід’ємною.")
    return value


def _options(entries):
    """Normalize option pairs into stable, sorted dictionary objects."""
    return [{"id": key, "name": name} for key, name in
            sorted(entries.items(), key=lambda x: (x[1].casefold(), str(x[0])))]


def _selected(key, options):
    """An omitted facet means all; malformed/stale submitted values mean none."""
    available = {str(item["id"]): item["id"] for item in options}
    raw = request.args.getlist(key)
    if not raw:
        return set(available.values()), list(available.values())
    if "__none__" in raw:
        return set(), []
    values = {available[value] for value in raw if value in available}
    return values, sorted(values, key=str)


def _load_fields(years):
    records = (
        FieldSeason.query.options(
            joinedload(FieldSeason.season),
            joinedload(FieldSeason.field),
            joinedload(FieldSeason.cluster),
            joinedload(FieldSeason.company),
            selectinload(FieldSeason.plantings).joinedload(FieldPlanting.culture),
        ).filter(FieldSeason.season_id.in_(
            [year.id for year in Season.query.filter(Season.year.in_(years)).all()]
        )).all()
    )
    rows = {}
    for fs in records:
        year = fs.season.year
        obj = rows.get(fs.field_id)
        if obj is None:
            obj = ReportRow(
                id=fs.field_id, name=fs.field.name,
                cluster_id=fs.cluster_id, cluster=fs.cluster.name,
                company_id=fs.company_id, company=fs.company.name,
                mass=_mass_prefix(fs.field.name),
            )
            rows[fs.field_id] = obj
        if year > obj.latest_year:
            obj.cluster_id, obj.cluster = fs.cluster_id, fs.cluster.name
            obj.company_id, obj.company = fs.company_id, fs.company.name
            obj.latest_year = year
        plantings = sorted(fs.plantings, key=lambda p: p.culture.name.casefold())
        obj.years[year] = YearCell(
            area=fs.area,
            crops=[CropCell(p.culture.name, p.area, p.note or "") for p in plantings],
        )
    return list(rows.values())


def _aggregate_masses(rows, selected_years):
    groups = {}
    for row in rows:
        key = (row.cluster_id, row.company_id, row.mass)
        current = groups.get(key)
        if current is None:
            current = ReportRow(
                id=0, name=row.mass, cluster_id=row.cluster_id,
                cluster=row.cluster, company_id=row.company_id,
                company=row.company, mass=row.mass, field_count=0,
            )
            groups[key] = current
        current.field_count += 1
        for year in selected_years:
            cell = row.years.get(year)
            if cell is None:
                continue
            target = current.years.setdefault(year, YearCell(area=Decimal("0.00")))
            target.area += cell.area
            crop_areas = {c.name: c for c in target.crops}
            for crop in cell.crops:
                if crop.name not in crop_areas:
                    copy = CropCell(name=crop.name, area=Decimal("0.00"))
                    target.crops.append(copy)
                    crop_areas[crop.name] = copy
                crop_areas[crop.name].area += crop.area
    for group in groups.values():
        for cell in group.years.values():
            cell.crops.sort(key=lambda c: c.name.casefold())
    return list(groups.values())


def _report_context():
    all_years = [s.year for s in Season.query.order_by(Season.year).all()]
    year_from = _year_param("year_from", all_years, all_years[0]) if all_years else None
    year_to = _year_param("year_to", all_years, all_years[-1]) if all_years else None
    if year_from is not None and year_from > year_to:
        abort(400, description="Початковий рік більший за кінцевий.")
    years = [y for y in all_years if year_from <= y <= year_to] if all_years else []
    crop_year_raw = request.args.get("crop_year", "")
    crop_year = _year_param("crop_year", all_years, None) if crop_year_raw else None
    if crop_year is not None and crop_year not in years:
        abort(400, description="Рік культури не входить до вибраного періоду.")
    mode = request.args.get("view", "fields")
    if mode not in ("fields", "masses"):
        abort(400, description="Невідомий спосіб групування.")

    area_min = _area_param("area_min")
    area_max = _area_param("area_max")
    if area_min is not None and area_max is not None and area_min > area_max:
        abort(400, description="Мінімальна площа більша за максимальну.")
    field_query = (request.args.get("q") or "").strip()
    if len(field_query) > 100:
        abort(400, description="Запит пошуку задовгий.")

    all_rows = _load_fields(years) if years else []
    cluster_options = _options({r.cluster_id: r.cluster for r in all_rows})
    clusters, selected_clusters = _selected("clusters", cluster_options)
    in_clusters = [r for r in all_rows if r.cluster_id in clusters]

    company_options = _options({r.company_id: r.company for r in in_clusters})
    companies, selected_companies = _selected("companies", company_options)
    in_companies = [r for r in in_clusters if r.company_id in companies]

    mass_options = _options({r.mass: r.mass for r in in_companies})
    masses, selected_masses = _selected("masses", mass_options)
    in_masses = [r for r in in_companies if r.mass in masses]

    def crop_ids_of(row):
        selected = [crop_year] if crop_year is not None else years
        names = {crop.name for y in selected for crop in
                 (row.years.get(y).crops if row.years.get(y) else [])}
        return names

    relevant_crop_names = set().union(*(crop_ids_of(r) for r in in_masses))
    culture_options = _options({
        c.id: c.name for c in Culture.query.filter(Culture.name.in_(relevant_crop_names)).all()
    }) if relevant_crop_names else []
    cultures, selected_cultures = _selected("cultures", culture_options)
    culture_by_id = {c["id"]: c["name"] for c in culture_options}
    requested_crops = {culture_by_id[c] for c in cultures}
    crop_filter_set = bool(request.args.getlist("cultures"))
    filtered = [
        r for r in in_masses
        if (not crop_filter_set or bool(crop_ids_of(r) & requested_crops))
        and (not field_query or field_query.casefold() in r.name.casefold())
        and (area_min is None and area_max is None or any(
            (area_min is None or cell.area >= area_min)
            and (area_max is None or cell.area <= area_max)
            for cell in r.years.values()
        ))
    ]
    filtered.sort(key=lambda r: (
        r.cluster.casefold(), r.company.casefold(), r.mass.casefold(), r.name.casefold()
    ))
    grouped = _aggregate_masses(filtered, years) if mode == "masses" else filtered
    grouped.sort(key=lambda r: (r.cluster.casefold(), r.company.casefold(), r.mass.casefold(), r.name.casefold()))

    raw_per_page = request.args.get("per_page", "100")
    if raw_per_page not in ("50", "100", "250"):
        abort(400, description="Некоректний розмір сторінки.")
    per_page = int(raw_per_page)
    raw_page = request.args.get("page", "1")
    if not raw_page.isdecimal() or int(raw_page) < 1:
        abort(400, description="Некоректний номер сторінки.")
    page_num = int(raw_page)
    total_pages = max(1, (len(grouped) + per_page - 1) // per_page)
    if page_num > total_pages:
        page_num = total_pages
    page_rows = grouped[(page_num - 1) * per_page:page_num * per_page]

    totals = {y: sum((r.years[y].area for r in filtered if y in r.years), Decimal("0.00"))
              for y in years}
    counts = {y: sum(y in r.years for r in filtered) for y in years}
    context = {
        "years": years, "all_years": all_years,
        "year_from": year_from, "year_to": year_to, "crop_year": crop_year,
        "mode": mode, "view_rows": grouped, "page_rows": page_rows,
        "page_num": page_num, "total_pages": total_pages, "per_page": per_page,
        "field_count": len(filtered), "group_count": len(grouped),
        "totals": totals, "year_counts": counts,
        "field_query": field_query, "area_min": area_min, "area_max": area_max,
        "facets": {
            "clusters": cluster_options, "companies": company_options,
            "masses": mass_options, "cultures": culture_options,
        },
        "checked": {
            "clusters": selected_clusters, "companies": selected_companies,
            "masses": selected_masses, "cultures": selected_cultures,
        },
    }
    return context


@rotation_bp.get("/structure/rotation")
def index():
    context = _report_context()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "html": render_template("rotation/_table.html", **context),
            "facets": context["facets"], "checked": context["checked"],
            "field_count": context["field_count"],
        })
    return render_template("rotation/index.html", **context)


def _safe_excel(value):
    """Protect CSV readers against spreadsheet formula injection."""
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_crops(cell):
    if not cell:
        return ""
    if len(cell.crops) == 1 and cell.crops[0].area == cell.area:
        return cell.crops[0].name + (
            f" [{cell.crops[0].note}]" if cell.crops[0].note else ""
        )
    return " | ".join(
        f"{c.name}: {c.area:.2f} га" for c in cell.crops
    )


@rotation_bp.get("/structure/rotation/csv")
def export_csv():
    """Download exactly the same filtered, read-only wide crop-rotation grid."""
    context = _report_context()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    headers = ["Кластер", "Підприємство", "Масив (префікс)", "Номер поля / масив"]
    if context["mode"] == "masses":
        headers.append("Кількість полів")
    for year in context["years"]:
        headers.extend((f"{year} Площа, га", f"{year} Культура"))
    writer.writerow(headers)
    for row in context["view_rows"]:
        cells = [row.cluster, row.company, row.mass, row.name]
        if context["mode"] == "masses":
            cells.append(row.field_count)
        for year in context["years"]:
            cell = row.years.get(year)
            cells.append(f"{cell.area:.2f}".replace(".", ",") if cell else "")
            cells.append(_csv_crops(cell))
        writer.writerow([_safe_excel(v) for v in cells])
    response = Response(
        "\ufeff" + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": (
            "attachment; filename=agroerp_sivozmina_"
            f"{context['year_from'] or 'none'}_{context['year_to'] or 'none'}.csv"
        )},
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
