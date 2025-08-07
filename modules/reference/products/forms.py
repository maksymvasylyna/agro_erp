# modules/reference/products/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms_sqlalchemy.fields import QuerySelectField

from modules.reference.categories.models import Category
from modules.reference.units.models import Unit
from modules.reference.groups.models import Group
from modules.reference.manufacturers.models import Manufacturer

class ProductForm(FlaskForm):
    name = StringField('Назва', validators=[DataRequired()])

    category = QuerySelectField(
        'Категорія',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=True
    )
    unit = QuerySelectField(
        'Одиниця виміру',
        query_factory=lambda: Unit.query.all(),
        get_label='name',
        allow_blank=True
    )
    group = QuerySelectField(
        'Група',
        query_factory=lambda: Group.query.all(),
        get_label='name',
        allow_blank=True
    )
    manufacturer = QuerySelectField(
        'Виробник',
        query_factory=lambda: Manufacturer.query.all(),
        get_label='name',
        allow_blank=True
    )

    container = StringField('Тара')

    submit = SubmitField('Зберегти')
class ProductFilterForm(FlaskForm):
    category = QuerySelectField(
        'Категорія',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=True
    )
    group = QuerySelectField(
        'Група',
        query_factory=lambda: Group.query.all(),
        get_label='name',
        allow_blank=True
    )
    manufacturer = QuerySelectField(
        'Виробник',
        query_factory=lambda: Manufacturer.query.all(),
        get_label='name',
        allow_blank=True
    )
    submit = SubmitField('Фільтрувати')
