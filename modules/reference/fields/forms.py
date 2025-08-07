# modules/reference/fields/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, FloatField
from wtforms_sqlalchemy.fields import QuerySelectField
from wtforms.validators import DataRequired

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture  # ✅ Імпорт

class FieldForm(FlaskForm):
    name = StringField('Назва', validators=[DataRequired()])

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

    area = FloatField('Площа')

    submit = SubmitField('Зберегти')


class FieldFilterForm(FlaskForm):
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
    culture = QuerySelectField(  # ✅ Нове!
        'Культура',
        query_factory=lambda: Culture.query.all(),
        get_label='name',
        allow_blank=True
    )
    submit = SubmitField('Фільтрувати')
