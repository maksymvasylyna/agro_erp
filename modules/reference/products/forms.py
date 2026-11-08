"""Product editor pulls current choices directly from master-data directories."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.shared_crud import normalize_reference_name
from modules.reference.categories.models import Category
from modules.reference.units.models import Unit
from modules.reference.groups.models import Group
from modules.reference.manufacturers.models import Manufacturer


def choices(model):
    return lambda: model.query.order_by(model.name).all()


class ProductForm(FlaskForm):
    name = StringField(
        "Назва продукту / препарату",
        filters=[normalize_reference_name],
        validators=[DataRequired(message="Вкажіть назву продукту."), Length(max=255)],
    )
    category = QuerySelectField(
        "Категорія", query_factory=choices(Category), get_label="name",
        allow_blank=True, blank_text="— Оберіть категорію —",
        validators=[DataRequired(message="Оберіть категорію.")],
    )
    unit = QuerySelectField(
        "Одиниця виміру", query_factory=choices(Unit), get_label="name",
        allow_blank=True, blank_text="— Оберіть одиницю —",
        validators=[DataRequired(message="Оберіть одиницю виміру.")],
    )
    group = QuerySelectField(
        "Група", query_factory=choices(Group), get_label="name",
        allow_blank=True, blank_text="— Оберіть групу —",
        validators=[DataRequired(message="Оберіть групу.")],
    )
    manufacturer = QuerySelectField(
        "Виробник", query_factory=choices(Manufacturer), get_label="name",
        allow_blank=True, blank_text="— Оберіть виробника —",
        validators=[DataRequired(message="Оберіть виробника.")],
    )
    container = StringField(
        "Тара", filters=[normalize_reference_name],
        validators=[Length(max=100)],
    )
    submit = SubmitField("Зберегти")


class ProductFilterForm(FlaskForm):
    class Meta:
        csrf = False

    category = QuerySelectField("Категорія", query_factory=choices(Category), get_label="name", allow_blank=True)
    group = QuerySelectField("Група", query_factory=choices(Group), get_label="name", allow_blank=True)
    manufacturer = QuerySelectField("Виробник", query_factory=choices(Manufacturer), get_label="name", allow_blank=True)
    submit = SubmitField("Фільтрувати")


class ProductDeleteForm(FlaskForm):
    """CSRF-protected deletion of an unreferenced product."""
