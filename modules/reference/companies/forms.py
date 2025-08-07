from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company

def cluster_query():
    clusters = Cluster.query.all()
    print("📦 Завантажено кластери:", [c.name for c in clusters])
    return clusters

class CompanyForm(FlaskForm):
    name = StringField('Назва', validators=[DataRequired()])
    cluster = QuerySelectField(
        'Кластер',
        query_factory=cluster_query,
        get_label='name',
        allow_blank=True,
        blank_text='— Оберіть кластер —'
    )
    submit = SubmitField('Зберегти')

class CompanyFilterForm(FlaskForm):
    name = QuerySelectField(
        'Підприємство',
        query_factory=lambda: Company.query.order_by(Company.name).all(),
        get_label='name',
        allow_blank=True,
        blank_text='— Оберіть підприємство —'
    )
    cluster = QuerySelectField(
        'Кластер',
        query_factory=cluster_query,
        get_label='name',
        allow_blank=True,
        blank_text='— Оберіть кластер —'
    )
    submit = SubmitField('Фільтрувати')
