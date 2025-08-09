from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from modules.reference.fields.field_models import Field
from modules.reference.fields.forms import FieldForm, FieldFilterForm

fields_bp = Blueprint('fields', __name__, template_folder='templates')


@fields_bp.route('/fields')
def index():
    form = FieldFilterForm(request.args)
    query = Field.query

    if form.cluster.data:
        query = query.filter_by(cluster_id=form.cluster.data.id)
    if form.company.data:
        query = query.filter_by(company_id=form.company.data.id)
    if form.culture.data:
        query = query.filter_by(culture_id=form.culture.data.id)

    fields = query.all()
    return render_template(
        'fields/index.html',
        form=form,
        items=fields,
        create_url=url_for('fields.create')  # ✅ для кнопки Додати
    )


@fields_bp.route('/fields/create', methods=['GET', 'POST'])
def create():
    form = FieldForm()
    if form.validate_on_submit():
        # 👉 Перевірка на дублікати
        existing = Field.query.filter_by(name=form.name.data).first()
        if existing:
            flash(f"Поле з назвою '{form.name.data}' вже існує!", "danger")
            return render_template(
                'fields/form.html',
                form=form,
                title='Нове поле',
                header='➕ Нове поле'
            )

        field = Field(
            name=form.name.data,
            cluster_id=form.cluster.data.id if form.cluster.data else None,
            company_id=form.company.data.id if form.company.data else None,
            culture_id=form.culture.data.id if form.culture.data else None,
            area=form.area.data
        )
        db.session.add(field)
        db.session.commit()
        flash('Поле додано!', 'success')
        return redirect(url_for('fields.index'))

    return render_template(
        'fields/form.html',
        form=form,
        title='Нове поле',
        header='➕ Нове поле'
    )


@fields_bp.route('/fields/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    field = Field.query.get_or_404(id)
    form = FieldForm(obj=field)
    if form.validate_on_submit():
        # 👉 Перевірка на дубль, якщо імʼя змінюється
        if field.name != form.name.data:
            existing = Field.query.filter_by(name=form.name.data).first()
            if existing:
                flash(f"Поле з назвою '{form.name.data}' вже існує!", "danger")
                return render_template(
                    'fields/form.html',
                    form=form,
                    title='Редагувати поле',
                    header='✏️ Редагувати поле'
                )

        field.name = form.name.data
        field.cluster_id = form.cluster.data.id if form.cluster.data else None
        field.company_id = form.company.data.id if form.company.data else None
        field.culture_id = form.culture.data.id if form.culture.data else None
        field.area = form.area.data
        db.session.commit()
        flash('Поле оновлено!', 'success')
        return redirect(url_for('fields.index'))

    return render_template(
        'fields/form.html',
        form=form,
        title='Редагувати поле',
        header='✏️ Редагувати поле'
    )


@fields_bp.route('/fields/<int:id>/delete', methods=['POST'])
def delete(id):
    field = Field.query.get_or_404(id)
    db.session.delete(field)
    db.session.commit()
    flash('Поле видалено!', 'info')
    return redirect(url_for('fields.index'))
