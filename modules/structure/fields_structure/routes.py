"""Season-aware field structure with hierarchical, multi-select column filters.

Facet order: cluster -> company -> crop -> field number -> planting area.
Multiple choices within a facet are OR-ed, and separate facets are AND-ed.
"""
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request, send_file, session
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


def _field_context():
    """Build exactly the same filtered dataset for the page and its PDF export."""
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

    return context


@fields_structure_bp.route("/structure/fields", methods=["GET"])
def index():
    context = _field_context()
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


def _pdf_font():
    """Use the project's bundled Cyrillic DejaVu font, not a system fallback."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "AgroDejaVu"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        project_root = Path(__file__).resolve().parents[3]
        font_path = project_root / "static" / "fonts" / "DejaVuSans.ttf"
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _pdf_filter_summary(context):
    """Human-readable active filter description, matching the table request."""
    labels = [
        ("clusters", "Кластери"),
        ("companies", "Підприємства"),
        ("cultures", "Культури"),
        ("fields", "Номери полів"),
    ]
    parts = []
    for key, title in labels:
        choices = context["options"][key]
        selected_ids = set(context["checked"][key])
        if len(selected_ids) == len(choices):
            continue
        selected = [entry.name for entry in choices if entry.id in selected_ids]
        if not selected:
            selection = "нічого не обрано"
        elif len(selected) <= 4:
            selection = ", ".join(selected)
        else:
            selection = f"обрано {len(selected)} із {len(choices)}"
        parts.append(f"{title}: {selection}")

    if context["area_min"] is not None or context["area_max"] is not None:
        lower = context["area_min"]
        upper = context["area_max"]
        bounds = (
            f"{lower if lower is not None else '0'} - "
            f"{upper if upper is not None else 'без обмеження'} га"
        )
        parts.append("Площа: " + bounds)
    return "; ".join(parts) if parts else "Усі поля та культури вибраного сезону"


@fields_structure_bp.route("/structure/fields/pdf", methods=["GET"])
def export_pdf():
    """Generate a multi-page Ukrainian PDF from the current season and query filters."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle,
    )

    context = _field_context()
    # A safeguard against accidentally generating unbounded reports.
    if context["count"] > 20000:
        abort(413, description="Завелика вибірка для PDF.")

    font = _pdf_font()
    navy = colors.HexColor("#17375E")
    gold = colors.HexColor("#D5AC3F")
    pale = colors.HexColor("#F3F6FA")
    grey = colors.HexColor("#5E6B78")

    title_style = ParagraphStyle(
        "AgroTitle", fontName=font, fontSize=14, leading=19,
        textColor=navy, spaceAfter=5,
    )
    info_style = ParagraphStyle(
        "AgroInfo", fontName=font, fontSize=8.5, leading=12,
        textColor=grey, spaceAfter=4,
    )
    head_style = ParagraphStyle(
        "AgroHead", fontName=font, fontSize=8, leading=10,
        textColor=colors.white, alignment=TA_LEFT,
    )
    body_style = ParagraphStyle(
        "AgroBody", fontName=font, fontSize=7.7, leading=10.5,
        textColor=navy,
    )
    body_right_style = ParagraphStyle(
        "AgroRight", parent=body_style, alignment=TA_RIGHT,
    )
    total_style = ParagraphStyle(
        "AgroTotal", fontName=font, fontSize=9, leading=13,
        textColor=navy, alignment=TA_RIGHT,
    )

    def paragraph(value, style):
        return Paragraph(escape(str(value)), style)

    year = context["season"].year if context["season"] else "не обрано"
    total_text = f"{context['total_area']:,.2f}".replace(",", " ").replace(".", ",")
    content = [
        paragraph(f"Структура по полях — урожай {year}", title_style),
        HRFlowable(width="100%", thickness=2, color=gold, spaceAfter=10),
        paragraph("Фільтри: " + _pdf_filter_summary(context), info_style),
        paragraph(
            f"Кількість посівів: {context['count']}  |  Площа вибірки: {total_text} га",
            info_style,
        ),
        Spacer(1, 7),
    ]

    headers = ["Кластер", "Підприємство", "Культура", "Номер поля", "Площа, га"]
    data = [[paragraph(h, head_style) for h in headers]]
    for planting in context["items"]:
        fs = planting.field_season
        area = f"{planting.area:,.2f}".replace(",", " ").replace(".", ",")
        data.append([
            paragraph(fs.cluster.name, body_style),
            paragraph(fs.company.name, body_style),
            paragraph(planting.culture.name, body_style),
            paragraph(fs.field.name, body_style),
            paragraph(area, body_right_style),
        ])
    if not context["items"]:
        data.append([
            paragraph("За вибраними фільтрами немає посівів", body_style),
            "", "", "", "",
        ])
    data.append([
        paragraph("Разом посівів", body_style), "", "", "",
        paragraph(total_text, body_right_style),
    ])

    pdf = BytesIO()
    doc = SimpleDocTemplate(
        pdf, pagesize=landscape(A4),
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=17 * mm,
        title=f"Структура полів — урожай {year}",
        author="AgroERP",
    )
    table = LongTable(
        data,
        colWidths=[103, 177, 160, 157, 100],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    last = len(data) - 1
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("ROWBACKGROUNDS", (0, 1), (-1, last - 1), [colors.white, pale]),
        ("LINEBELOW", (0, 0), (-1, 0), 1, gold),
        ("LINEBELOW", (0, 1), (-1, last - 1), 0.25, colors.HexColor("#E2E8F0")),
        ("BACKGROUND", (0, last), (-1, last), colors.HexColor("#FFF3CC")),
        ("LINEABOVE", (0, last), (-1, last), 1, gold),
        ("SPAN", (0, last), (3, last)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)

    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(grey)
        canvas.drawString(15 * mm, 9 * mm, f"AgroERP | Урожай {year}")
        canvas.drawRightString(
            landscape(A4)[0] - 15 * mm, 9 * mm,
            f"Сторінка {document.page}",
        )
        canvas.restoreState()

    doc.build(content, onFirstPage=page_footer, onLaterPages=page_footer)
    pdf.seek(0)

    response = send_file(
        pdf, mimetype="application/pdf", as_attachment=True,
        download_name=f"struktura_poliv_{year}.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
