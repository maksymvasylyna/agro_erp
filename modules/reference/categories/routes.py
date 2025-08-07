from flask import Blueprint, render_template, redirect, url_for, request, flash
from .models import Category
from .forms import CategoryForm
from extensions import db

bp = Blueprint("categories", __name__, url_prefix="/categories", template_folder="templates")

@bp.route("/")
def index():
    categories = Category.query.order_by(Category.name).all()
    return render_template(
        "categories/index.html",
        categories=categories,
        create_url=url_for("categories.create")  # ✅ передаємо сюди
    )

@bp.route("/create", methods=["GET", "POST"])
def create():
    form = CategoryForm()
    if form.validate_on_submit():
        new_category = Category(name=form.name.data)
        db.session.add(new_category)
        db.session.commit()
        flash("Категорію додано", "success")
        return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form)

@bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    category = Category.query.get_or_404(id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        category.name = form.name.data
        db.session.commit()
        flash("Категорію оновлено", "success")
        return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form)

@bp.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    category = Category.query.get_or_404(id)
    db.session.delete(category)
    db.session.commit()
    flash("Категорію видалено", "info")
    return redirect(url_for("categories.index"))
