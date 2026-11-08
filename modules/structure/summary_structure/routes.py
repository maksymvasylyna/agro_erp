"""Crop-area summary for one selected harvest season.

Rows are enterprises, columns are crops. Switching the global harvest year
changes the query but preserves the current report and cluster filter.
"""
from collections import defaultdict
from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path

from flask import Blueprint, render_template, request, send_file
from sqlalchemy import func

from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.season_models import FieldPlanting, FieldSeason
from modules.reference.fields.routes import _view_context

bp = Blueprint(
    "summary_structure", __name__, url_prefix="/summary_structure",
    template_folder="templates",
)

ZERO = Decimal("0.00")


@bp.app_template_filter("ua_area")
def ua_area(value):
    """Format hectares to two decimals using Ukrainian separators."""
    return f"{Decimal(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _summary_context():
    """Shared season/cluster result for the HTML table and PDF export."""
    common = _view_context()
    season = common["season"]

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

    return dict(
        **common,
        matrix=matrix,
        crops=crops,
        cluster_totals=cluster_totals,
        grand_totals=grand_totals,
        cluster_options=cluster_options,
        selected_cluster=selected_cluster,
    )


@bp.route("/", methods=["GET"])
def index():
    return render_template("summary_structure/index.html", **_summary_context())


def _pdf_font():
    """Register the bundled Unicode font, including Ukrainian glyphs."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    name = "AgroDejaVu"
    if name not in pdfmetrics.getRegisteredFontNames():
        root = Path(__file__).resolve().parents[3]
        pdfmetrics.registerFont(TTFont(name, str(root / "static" / "fonts" / "DejaVuSans.ttf")))
    return name


@bp.route("/pdf", methods=["GET"])
def export_pdf():
    """Download the exact selected-season, selected-cluster crop pivot as PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle,
    )

    report = _summary_context()
    crops = report["crops"]
    matrix = report["matrix"]
    font = _pdf_font()
    navy = colors.HexColor("#17375E")
    gold = colors.HexColor("#D5AC3F")
    pale = colors.HexColor("#F2F5F9")
    light_blue = colors.HexColor("#E5EDF7")
    grey = colors.HexColor("#667383")

    page = landscape(A3 if len(crops) > 7 else A4)
    side_margin = 13 * mm
    drawable = page[0] - 2 * side_margin
    company_width = min(192 if len(crops) > 7 else 150, drawable * 0.28)
    total_width = 83 if len(crops) > 7 else 78
    numeric_width = (drawable - company_width - total_width) / max(1, len(crops))
    widths = [company_width] + [numeric_width] * len(crops) + [total_width]

    title_style = ParagraphStyle(
        "SummaryTitle", fontName=font, fontSize=14, leading=19,
        textColor=navy, spaceAfter=7,
    )
    meta_style = ParagraphStyle(
        "SummaryMeta", fontName=font, fontSize=8.5, leading=13,
        textColor=grey, spaceAfter=4,
    )
    label_style = ParagraphStyle(
        "SummaryBody", fontName=font, fontSize=7.5, leading=10,
        textColor=navy,
    )
    number_style = ParagraphStyle(
        "SummaryNumber", parent=label_style, alignment=TA_RIGHT,
    )
    head_style = ParagraphStyle(
        "SummaryHead", fontName=font, fontSize=7.5, leading=10,
        alignment=TA_CENTER, textColor=colors.white,
    )
    sub_style = ParagraphStyle(
        "SummarySubtotal", fontName=font, fontSize=7.5, leading=11,
        textColor=navy,
    )

    def paragraph(value, style):
        return Paragraph(escape(str(value)), style)

    def hectares(value):
        return f"{Decimal(value or 0):,.2f}".replace(",", " ").replace(".", ",")

    year = report["season"].year if report["season"] else "не обрано"
    cluster = next(
        (c.name for c in report["cluster_options"] if c.id == report["selected_cluster"]),
        "Усі кластери",
    )
    overall = sum(report["grand_totals"].values(), ZERO)
    narrative = [
        paragraph(f"Загальна структура посівних площ — урожай {year}", title_style),
        HRFlowable(width="100%", thickness=2, color=gold, spaceAfter=10),
        paragraph(f"Кластер: {cluster}", meta_style),
        paragraph(f"Площа посівів: {hectares(overall)} га", meta_style),
        Spacer(1, 7),
    ]

    headers = ["Підприємство"] + crops + ["Разом, га"]
    cells = [[paragraph(h, head_style) for h in headers]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("LINEBELOW", (0, 0), (-1, 0), 1, gold),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    body_index = 0
    for group, companies in matrix.items():
        group_row = len(cells)
        cells.append([paragraph(group, sub_style)] + [""] * (len(headers) - 1))
        styles.extend([
            ("SPAN", (0, group_row), (-1, group_row)),
            ("BACKGROUND", (0, group_row), (-1, group_row), light_blue),
            ("LINEABOVE", (0, group_row), (-1, group_row), 0.75, gold),
        ])
        for company, areas in companies.items():
            row_index = len(cells)
            crop_values = [areas.get(crop, ZERO) for crop in crops]
            cells.append(
                [paragraph(company, label_style)]
                + [paragraph(hectares(v), number_style) for v in crop_values]
                + [paragraph(hectares(sum(crop_values, ZERO)), number_style)]
            )
            if body_index % 2:
                styles.append(("BACKGROUND", (0, row_index), (-1, row_index), pale))
            body_index += 1
        subtotal_row = len(cells)
        totals = [report["cluster_totals"][group][crop] for crop in crops]
        cells.append(
            [paragraph(f"Разом — {group}", sub_style)]
            + [paragraph(hectares(v), number_style) for v in totals]
            + [paragraph(hectares(sum(totals, ZERO)), number_style)]
        )
        styles.extend([
            ("BACKGROUND", (0, subtotal_row), (-1, subtotal_row), light_blue),
            ("LINEABOVE", (0, subtotal_row), (-1, subtotal_row), 0.5, gold),
        ])

    if not matrix:
        empty = len(cells)
        cells.append([paragraph("Для вибраного сезону та кластера немає посівів", label_style)]
                     + [""] * (len(headers) - 1))
        styles.append(("SPAN", (0, empty), (-1, empty)))

    grand_row = len(cells)
    cells.append(
        [paragraph("Разом", sub_style)]
        + [paragraph(hectares(report["grand_totals"][crop]), number_style) for crop in crops]
        + [paragraph(hectares(overall), number_style)]
    )
    styles.extend([
        ("BACKGROUND", (0, grand_row), (-1, grand_row), colors.HexColor("#FFF2C6")),
        ("LINEABOVE", (0, grand_row), (-1, grand_row), 1.25, gold),
    ])
    table = LongTable(cells, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(TableStyle(styles))
    narrative.append(table)

    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=page,
        leftMargin=side_margin, rightMargin=side_margin,
        topMargin=15 * mm, bottomMargin=17 * mm,
        title=f"Загальна структура посівів — урожай {year}",
        author="AgroERP",
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(grey)
        canvas.drawString(side_margin, 9 * mm, f"AgroERP | Урожай {year}")
        canvas.drawRightString(page[0] - side_margin, 9 * mm, f"Сторінка {document.page}")
        canvas.restoreState()

    doc.build(narrative, onFirstPage=footer, onLaterPages=footer)
    stream.seek(0)
    response = send_file(
        stream, mimetype="application/pdf", as_attachment=True,
        download_name=f"zagalna_struktura_{year}.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
