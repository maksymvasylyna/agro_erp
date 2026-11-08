from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from .models import Group
from .forms import GroupForm

bp = Blueprint("groups", __name__, url_prefix="/groups", template_folder="templates")

@bp.route("/")
def index():
    groups = Group.query.all()
    return render_template(
        "groups/index.html",
        groups=groups,
        create_url=url_for("groups.create")  # ✅ Обовʼязково!
    )


@bp.route("/create", methods=["GET", "POST"])
def create():
    form = GroupForm()
    if form.validate_on_submit():
        new_group = Group(name=form.name.data)
        db.session.add(new_group)
        db.session.commit()
        flash("Групу додано", "success")
        return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Створити")

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    group = Group.query.get_or_404(id)
    form = GroupForm(obj=group)
    if form.validate_on_submit():
        group.name = form.name.data
        db.session.commit()
        flash("Групу оновлено", "success")
        return redirect(url_for("groups.index"))
    return render_template("groups/form.html", form=form, action="Редагувати")

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    group = Group.query.get_or_404(id)
    db.session.delete(group)
    db.session.commit()
    flash("Групу видалено", "info")
    return redirect(url_for("groups.index"))