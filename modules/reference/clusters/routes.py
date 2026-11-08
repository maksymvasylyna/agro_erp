"""Reference directory for clusters, consumed by companies and fields."""
from flask import Blueprint, render_template, redirect, url_for, flash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.reference.companies.models import Company
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import FieldSeason
from .models import Cluster
from .forms import ClusterForm, ClusterDeleteForm, normalize_cluster_name

bp = Blueprint("clusters", __name__, url_prefix="/clusters", template_folder="templates")


def _existing_cluster(name, exclude_id=None):
    query = Cluster.query.filter(func.lower(Cluster.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Cluster.id != exclude_id)
    return query.first()


def _counts():
    companies = dict(
        db.session.query(Company.cluster_id, func.count(Company.id))
        .group_by(Company.cluster_id).all()
    )
    # Include permanent fields and seasonal affiliations, without
    # double-counting the same field within a cluster across years.
    linked = {}
    for cluster_id, field_id in db.session.query(Field.cluster_id, Field.id).all():
        if cluster_id is not None:
            linked.setdefault(cluster_id, set()).add(field_id)
    for cluster_id, field_id in db.session.query(
        FieldSeason.cluster_id, FieldSeason.field_id
    ).all():
        linked.setdefault(cluster_id, set()).add(field_id)
    fields = {cluster_id: len(ids) for cluster_id, ids in linked.items()}
    return companies, fields


@bp.route("/")
def index():
    clusters = Cluster.query.order_by(Cluster.name).all()
    company_counts, field_counts = _counts()
    return render_template(
        "clusters/index.html",
        clusters=clusters,
        company_counts=company_counts,
        field_counts=field_counts,
        delete_form=ClusterDeleteForm(),
        create_url=url_for("clusters.create"),
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = ClusterForm()
    if form.validate_on_submit():
        name = normalize_cluster_name(form.name.data)
        if _existing_cluster(name):
            form.name.errors.append("Кластер із такою назвою вже існує.")
        else:
            try:
                db.session.add(Cluster(name=name))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти кластер: назва вже використовується.")
            else:
                flash("Кластер додано.", "success")
                return redirect(url_for("clusters.index"))
    return render_template("clusters/form.html", form=form, action="Створити")


@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    cluster = Cluster.query.get_or_404(id)
    form = ClusterForm(obj=cluster)
    if form.validate_on_submit():
        name = normalize_cluster_name(form.name.data)
        if _existing_cluster(name, exclude_id=cluster.id):
            form.name.errors.append("Кластер із такою назвою вже існує.")
        else:
            cluster.name = name
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.name.errors.append("Не вдалося зберегти: така назва вже використовується.")
            else:
                flash("Кластер оновлено.", "success")
                return redirect(url_for("clusters.index"))
    return render_template("clusters/form.html", form=form, action="Редагувати")


@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    form = ClusterDeleteForm()
    if not form.validate_on_submit():
        flash("Невірне або прострочене підтвердження видалення.", "warning")
        return redirect(url_for("clusters.index"))

    cluster = Cluster.query.get_or_404(id)
    companies = Company.query.filter_by(cluster_id=cluster.id).count()
    fields = Field.query.filter_by(cluster_id=cluster.id).count()
    seasonal_fields = FieldSeason.query.filter_by(cluster_id=cluster.id).count()
    if companies or fields or seasonal_fields:
        flash(
            f"Кластер «{cluster.name}» використовується: підприємств — {companies}, "
            f"постійних полів — {fields}, сезонних записів — {seasonal_fields}. "
            "Спочатку змініть їх прив'язки; видалення заблоковано.",
            "warning",
        )
        return redirect(url_for("clusters.index"))

    try:
        db.session.delete(cluster)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Кластер має пов'язані записи й не може бути видалений.", "warning")
    else:
        flash("Кластер видалено.", "info")
    return redirect(url_for("clusters.index"))
