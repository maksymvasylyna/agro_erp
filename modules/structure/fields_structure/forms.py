# modules/structure/fields_structure/forms.py

from flask_wtf import FlaskForm
from wtforms_sqlalchemy.fields import QuerySelectField
from wtforms import SubmitField
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture

class FieldsStructureFilterForm(FlaskForm):
    cluster = QuerySelectField(
        'Кластер',
        query_factory=lambda: Cluster.query.all(),
        get_label='name',
        allow_blank=True
    )
    company = QuerySelectField(
        'Підприємство',
        query_factory=lambda: Company.query.all(),
        get_label='name',
        allow_blank=True
    )
    culture = QuerySelectField(
        'Культура',
        query_factory=lambda: Culture.query.all(),
        get_label='name',
        allow_blank=True
    )
    submit = SubmitField('Фільтрувати')
