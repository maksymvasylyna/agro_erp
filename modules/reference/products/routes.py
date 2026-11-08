from flask import Blueprint, render_template, redirect, url_for, request
from extensions import db
from modules.reference.products.models import Product
from modules.reference.products.forms import ProductForm, ProductFilterForm

products_bp = Blueprint('products', __name__, template_folder='templates')

# 🗂️ Список продуктів з фільтрацією
@products_bp.route('/products')
def index():
    form = ProductFilterForm(request.args)
    query = Product.query

    if form.category.data:
        query = query.filter_by(category_id=form.category.data.id)
    if form.group.data:
        query = query.filter_by(group_id=form.group.data.id)
    if form.manufacturer.data:
        query = query.filter_by(manufacturer_id=form.manufacturer.data.id)

    products = query.all()
    return render_template(
        'products/index.html',
        form=form,
        items=products,
        create_url=url_for('products.create')  # ✅ додай це!
    )


# ➕ Створення продукту
@products_bp.route('/products/create', methods=['GET', 'POST'])
def create():
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            category_id=form.category.data.id if form.category.data else None,
            unit_id=form.unit.data.id if form.unit.data else None,
            group_id=form.group.data.id if form.group.data else None,
            manufacturer_id=form.manufacturer.data.id if form.manufacturer.data else None,
            container=form.container.data
        )
        db.session.add(product)
        db.session.commit()
        return redirect(url_for('products.index'))
    return render_template(
        'products/form.html',
        form=form
    )

# ✏️ Редагування продукту
@products_bp.route('/products/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    product = Product.query.get_or_404(id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        product.name = form.name.data
        product.category_id = form.category.data.id if form.category.data else None
        product.unit_id = form.unit.data.id if form.unit.data else None
        product.group_id = form.group.data.id if form.group.data else None
        product.manufacturer_id = form.manufacturer.data.id if form.manufacturer.data else None
        product.container = form.container.data
        db.session.commit()
        return redirect(url_for('products.index'))
    return render_template(
        'products/form.html',
        form=form
    )

# 🗑️ Видалення продукту
@products_bp.route('/products/<int:id>/delete', methods=['POST'])
def delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for('products.index'))
