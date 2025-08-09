# modules/structure/summary_structure/routes.py

from flask import Blueprint, render_template, request
from extensions import db
from modules.structure.summary_structure.forms import SummaryStructureFilterForm
from modules.reference.fields.field_models import Field
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture

bp = Blueprint(
    "summary_structure",
    __name__,
    url_prefix="/summary_structure",
    template_folder="templates"
)

@bp.route("/", methods=["GET", "POST"])
def index():
    form = SummaryStructureFilterForm(request.form)

    query = (
        db.session.query(
            Cluster.name.label("cluster"),
            Company.name.label("company"),
            Culture.name.label("culture"),
            db.func.sum(Field.area).label("total_area")
        )
        .join(Cluster, Field.cluster_id == Cluster.id)
        .join(Company, Field.company_id == Company.id)
        .join(Culture, Field.culture_id == Culture.id)
    )

    if form.validate_on_submit():
        if form.season_year.data:
            query = query.filter(Field.season_year == form.season_year.data)
        if form.cluster.data:
            query = query.filter(Field.cluster_id == form.cluster.data.id)

    query = query.group_by(Cluster.name, Company.name, Culture.name).order_by(Cluster.name, Company.name, Culture.name)
    data = query.all()

    # Формуємо структуру: {cluster: {company: {culture: area}}}
    result = {}
    clusters = set()
    cultures = set()

    for row in data:
        result.setdefault(row.cluster, {}).setdefault(row.company, {})[row.culture] = row.total_area
        clusters.add(row.cluster)
        cultures.add(row.culture)

    cultures = sorted(cultures)
    clusters = sorted(clusters)

    # Підсумки
    cluster_totals = {}   # {cluster: {culture: area, 'Разом': ...}}
    company_totals = {}   # {cluster: {company: total_area}}
    total_row = {}        # {culture: area, 'Разом': ...}

    for cluster in clusters:
        cluster_totals[cluster] = {}
        company_totals[cluster] = {}
        for company, cultures_areas in result[cluster].items():
            company_total = sum(cultures_areas.values())
            company_totals[cluster][company] = company_total
            for culture in cultures:
                cluster_totals[cluster][culture] = cluster_totals[cluster].get(culture, 0) + cultures_areas.get(culture, 0)
        cluster_totals[cluster]['Разом'] = sum(cluster_totals[cluster].values())

    for culture in cultures:
        total_row[culture] = sum(cluster_totals[cluster].get(culture, 0) for cluster in clusters)
    total_row['Разом'] = sum(total_row.values())

    return render_template(
        "summary_structure/index.html",
        form=form,
        result=result,
        clusters=clusters,
        cultures=cultures,
        company_totals=company_totals,
        cluster_totals=cluster_totals,
        total_row=total_row
    )
