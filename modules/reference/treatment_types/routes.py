from flask import Blueprint, render_template, redirect, url_for, request
from extensions import db
from .models import TreatmentType
from .forms import TreatmentTypeForm

treatment_types_bp = Blueprint(
    'treatment_types',
    __name__,
    url_prefix='/reference/treatment_types',
    template_folder='templates'
)

@treatment_types_bp.route('/')
def index():
    items = db.session.query(TreatmentType).order_by(TreatmentType.name).all()
    return render_template(
        'treatment_types/index.html',
        items=items,
        create_url=url_for('treatment_types.create')  # ← ось ця зміна
    )

@treatment_types_bp.route('/create', methods=['GET', 'POST'])
def create():
    form = TreatmentTypeForm()
    if form.validate_on_submit():
        item = TreatmentType(name=form.name.data)
        db.session.add(item)
        db.session.commit()
        return redirect(url_for('treatment_types.index'))
    return render_template('treatment_types/form.html', form=form)

@treatment_types_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
def edit(item_id):
    item = db.session.get(TreatmentType, item_id)
    form = TreatmentTypeForm(obj=item)
    if form.validate_on_submit():
        item.name = form.name.data
        db.session.commit()
        return redirect(url_for('treatment_types.index'))
    return render_template('treatment_types/form.html', form=form, item=item)

@treatment_types_bp.route('/delete/<int:item_id>', methods=['POST'])
def delete(item_id):
    item = db.session.get(TreatmentType, item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('treatment_types.index'))
