"""Forms for products, using live choices from the reference directories."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from wtforms_sqlalchemy.fields import QuerySelectField

from modules.reference.shared_crud import normalize_reference_name
from modules.reference.categories.models import Category
from modules.reference.units.models import Unit
from modules.reference.groups.models import Group
from modules.reference.manufacturers.models import Manufacturer


def _choices(model):
    return lambda: model.query.order_by(model.name).all()


class ProductForm(FlaskForm):
    name = StringField(
        "Назва продукту / препарату",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву продукту."),
            Length(max=255, message="Назва не може перевищувати 255 символів."),
        ],
    )
    category = QuerySelectField(
        "Категорія",
        query_factory=_choices(Category),
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть категорію —",
        validators=[DataRequired(message="Оберіть категорію.")],
    )
    group = QuerySelectField(
        "Група",
        query_factory=_choices(Group),
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть групу —",
        validators=[DataRequired(message="Оберіть групу.")],
    )
    manufacturer = QuerySelectField(
        "Виробник",
        query_factory=_choices(Manufacturer),
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть виробника —",
        validators=[DataRequired(message="Оберіть виробника.")],
    )
    unit = QuerySelectField(
        "Одиниця виміру",
        query_factory=_choices(Unit),
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть одиницю виміру —",
        validators=[DataRequired(message="Оберіть одиницю виміру.")],
    )
    container = StringField(
        "Тара",
        filters=[normalize_reference_name],
        validators=[Length(max=100, message="Тара не може перевищувати 100 символів.")],
    )
    submit = SubmitField("Зберегти")


class ProductFilterForm(FlaskForm):
    class Meta:
        csrf = False  # Read-only GET filter, unlike mutation forms.

    category = QuerySelectField(
        "Категорія", query_factory=_choices(Category), get_label="name",
        allow_blank=True, blank_text="— Усі категорії —",
    )
    group = QuerySelectField(
        "Група", query_factory=_choices(Group), get_label="name",
        allow_blank=True, blank_text="— Усі групи —",
    )
    manufacturer = QuerySelectField(
        "Виробник", query_factory=_choices(Manufacturer), get_label="name",
        allow_blank=True, blank_text="— Усі виробники —",
    )
    submit = SubmitField("Фільтрувати")


class ProductDeleteForm(FlaskForm):
    """CSRF-protected deletion of unused products."""
