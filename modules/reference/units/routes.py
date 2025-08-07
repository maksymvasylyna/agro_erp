from flask import Blueprint, render_template, redirect, url_for, request, flash
from modules.reference.units.models import Unit
from modules.reference.units.forms import UnitForm
from extensions import db

bp = Blueprint('units', __name__, template_folder='templates')

@bp.route('/units')
def index():
    units = Unit.query.order_by(Unit.name).all()
    return render_template(
        'units/index.html',
        units=units,
        create_url=url_for('units.create')
    )

@bp.route('/units/create', methods=['GET', 'POST'])
def create():
    form = UnitForm()
    if form.validate_on_submit():
        unit = Unit(name=form.name.data)
        db.session.add(unit)
        db.session.commit()
        flash('Одиницю додано успішно!', 'success')
        return redirect(url_for('units.index'))
    return render_template('units/form.html', form=form, title='Додати одиницю')

@bp.route('/units/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    unit = Unit.query.get_or_404(id)
    form = UnitForm(obj=unit)
    if form.validate_on_submit():
        unit.name = form.name.data
        db.session.commit()
        flash('Зміни збережено!', 'success')
        return redirect(url_for('units.index'))
    return render_template('units/form.html', form=form, title='Редагувати одиницю')

@bp.route('/units/delete/<int:id>', methods=['POST'])
def delete(id):
    unit = Unit.query.get_or_404(id)
    db.session.delete(unit)
    db.session.commit()
    flash('Одиницю видалено!', 'warning')
    return redirect(url_for('units.index'))
