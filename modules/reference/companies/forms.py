from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, ValidationError
from wtforms_sqlalchemy.fields import QuerySelectField
from sqlalchemy import func

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company


def cluster_query():
    # Сортуємо для зручності у випадаючому списку
    return Cluster.query.order_by(Cluster.name).all()


class CompanyForm(FlaskForm):
    """
    Форма створення/редагування компанії.
    ПРИ РЕДАГУВАННІ передавай obj_id=company.id, щоб не глючив дубль на себе.
    """
    name = StringField('Назва', validators=[DataRequired()])
    cluster = QuerySelectField(
        'Кластер',
        query_factory=cluster_query,
        get_label='name',
        allow_blank=True,
        blank_text='— Оберіть кластер —'
    )
    submit = SubmitField('Зберегти')

    def __init__(self, *args, **kwargs):
        self.obj_id = kwargs.pop('obj_id', None)  # id поточного запису під час редагування
        super().__init__(*args, **kwargs)

    def validate_name(self, field):
        name = (field.data or '').strip()
        if not name:
            return
        q = Company.query.filter(func.lower(Company.name) == func.lower(name))
        if self.obj_id:
            q = q.filter(Company.id != self.obj_id)
        if q.first():
            raise ValidationError('Компанія з такою назвою вже існує.')


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
