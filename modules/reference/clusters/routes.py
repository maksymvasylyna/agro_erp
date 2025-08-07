# modules/reference/clusters/routes.py

from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Cluster
from .forms import ClusterForm

bp = Blueprint("clusters", __name__, url_prefix="/clusters", template_folder="templates")

@bp.route("/")
def index():
    clusters = Cluster.query.order_by(Cluster.name).all()
    return render_template(
        "clusters/index.html",
        clusters=clusters,
        create_url=url_for("clusters.create")  # ✅ Ось і все!
    )

@bp.route("/create", methods=["GET", "POST"])
def create():
    form = ClusterForm()
    if form.validate_on_submit():
        new_cluster = Cluster(name=form.name.data)
        db.session.add(new_cluster)
        db.session.commit()
        flash("Кластер додано", "success")
        return redirect(url_for("clusters.index"))
    return render_template("clusters/form.html", form=form, action="Створити")

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    cluster = Cluster.query.get_or_404(id)
    form = ClusterForm(obj=cluster)
    if form.validate_on_submit():
        cluster.name = form.name.data
        db.session.commit()
        flash("Кластер оновлено", "success")
        return redirect(url_for("clusters.index"))
    return render_template("clusters/form.html", form=form, action="Редагувати")

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    cluster = Cluster.query.get_or_404(id)
    db.session.delete(cluster)
    db.session.commit()
    flash("Кластер видалено", "info")
    return redirect(url_for("clusters.index"))
