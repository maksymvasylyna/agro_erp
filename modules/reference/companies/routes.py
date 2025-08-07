from flask import Blueprint, render_template, redirect, url_for, request, flash
from extensions import db
from modules.reference.companies.models import Company
from modules.reference.companies.forms import CompanyForm, CompanyFilterForm

companies_bp = Blueprint('companies', __name__, template_folder='templates')

@companies_bp.route('/companies')
def index():
    form = CompanyFilterForm(request.args)
    query = Company.query

    if form.name.data:
        query = query.filter_by(id=form.name.data.id)  # ✅ фільтр по ID обраної компанії
    if form.cluster.data:
        query = query.filter_by(cluster_id=form.cluster.data.id)

    companies = query.order_by(Company.name).all()

    items = [
        (
            c.id, c.name, c.cluster.name if c.cluster else '—',
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

    # 🧪 Діагностика (залишай за потреби)
    clusters = form.cluster.query_factory()
    print("📦 Кластери у query_factory:", [f"{c.id} – {c.name}" for c in clusters])

    if form.validate_on_submit():
        new_company = Company(
            name=form.name.data,
            cluster=form.cluster.data
        )
        db.session.add(new_company)
        db.session.commit()
        flash('Підприємство додано успішно.', 'success')
        return redirect(url_for('companies.index'))

    return render_template(
        'companies/form.html',
        form=form,
        title='Нове підприємство',
        header='➕ Нове підприємство'
    )

@companies_bp.route('/companies/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    company = Company.query.get_or_404(id)
    form = CompanyForm(obj=company)

    if form.validate_on_submit():
        company.name = form.name.data
        company.cluster = form.cluster.data
        db.session.commit()
        flash('Зміни збережено.', 'success')
        return redirect(url_for('companies.index'))

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
