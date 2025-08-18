from flask import Blueprint, render_template, redirect, url_for, request, flash
from sqlalchemy.exc import IntegrityError
from extensions import db
from modules.reference.companies.models import Company
from modules.reference.companies.forms import CompanyForm, CompanyFilterForm

companies_bp = Blueprint('companies', __name__, template_folder='templates')

@companies_bp.route('/companies')
def index():
    form = CompanyFilterForm(request.args)
    query = Company.query

    if form.name.data:
        query = query.filter_by(id=form.name.data.id)  # ✅ фільтр по вибраній компанії
    if form.cluster.data:
        query = query.filter_by(cluster_id=form.cluster.data.id)

    companies = query.order_by(Company.name).all()

    items = [
        (
            c.id,
            c.name,
            c.cluster.name if c.cluster else '—',
            url_for('companies.edit', id=c.id),
            url_for('companies.delete', id=c.id)
        )
        for c in companies
    ]

    return render_template(
        'companies/index.html',
        form=form,
        items=items,
        title='Підприємства',
        header='🏢 Підприємства',
        create_url=url_for('companies.create')
    )

@companies_bp.route('/companies/create', methods=['GET', 'POST'])
def create():
    form = CompanyForm()

    if form.validate_on_submit():
        new_company = Company(
            name=(form.name.data or '').strip(),
            cluster=form.cluster.data  # QuerySelectField повертає об’єкт або None
        )
        db.session.add(new_company)
        try:
            db.session.commit()
            flash('Підприємство додано успішно.', 'success')
            return redirect(url_for('companies.index'))
        except IntegrityError:
            db.session.rollback()
            # Страхуємося на випадок гонки або різниці в регістрі
            form.name.errors.append('Компанія з такою назвою вже існує (БД).')

    return render_template(
        'companies/form.html',
        form=form,
        title='Нове підприємство',
        header='➕ Нове підприємство'
    )

@companies_bp.route('/companies/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    company = Company.query.get_or_404(id)
    # важливо: передати obj_id, щоб валідатор не вважав поточний запис дублем
    form = CompanyForm(obj=company, obj_id=company.id)

    if form.validate_on_submit():
        company.name = (form.name.data or '').strip()
        company.cluster = form.cluster.data
        try:
            db.session.commit()
            flash('Зміни збережено.', 'success')
            return redirect(url_for('companies.index'))
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append('Компанія з такою назвою вже існує (БД).')

    return render_template(
        'companies/form.html',
        form=form,
        title='Редагування підприємства',
        header='✏️ Редагування підприємства'
    )

@companies_bp.route('/companies/delete/<int:id>', methods=['POST'])
def delete(id):
    company = Company.query.get_or_404(id)
    db.session.delete(company)
    db.session.commit()
    flash('Підприємство видалено.', 'warning')
    return redirect(url_for('companies.index'))
