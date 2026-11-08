"""Input validation for permanent fields, seasons and crop rotation."""
from decimal import Decimal
from flask_wtf import FlaskForm
from wtforms import DecimalField, IntegerField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from wtforms_sqlalchemy.fields import QuerySelectField

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture


def normalize_field_name(name):
    return " ".join((name or "").split())


def _clusters():
    return Cluster.query.order_by(Cluster.name).all()


def _companies():
    return Company.query.order_by(Company.name).all()


def _cultures():
    return Culture.query.order_by(Culture.name).all()


class FieldCreateForm(FlaskForm):
    name = StringField(
        "Номер / назва поля", filters=[normalize_field_name],
        validators=[DataRequired(message="Вкажіть номер поля."), Length(max=255)],
    )
    cluster = QuerySelectField(
        "Кластер", query_factory=_clusters, get_label="name",
        allow_blank=True, blank_text="— Оберіть кластер —",
        validators=[DataRequired(message="Оберіть кластер.")],
    )
    company = QuerySelectField(
        "Підприємство", query_factory=_companies, get_label="name",
        allow_blank=True, blank_text="— Оберіть підприємство —",
        validators=[DataRequired(message="Оберіть підприємство.")],
    )
    area = DecimalField(
        "Фізична площа, га", places=2,
        validators=[DataRequired(message="Вкажіть площу."), NumberRange(min=Decimal("0.01"))],
    )
    culture = QuerySelectField(
        "Початкова культура (необов'язково)", query_factory=_cultures, get_label="name",
        allow_blank=True, blank_text="— Поки не визначено —",
    )
    submit = SubmitField("Створити поле")


class FieldNameForm(FlaskForm):
    name = StringField(
        "Постійний номер / назва поля", filters=[normalize_field_name],
        validators=[DataRequired(message="Вкажіть номер поля."), Length(max=255)],
    )
    submit = SubmitField("Зберегти")


class SeasonFieldForm(FlaskForm):
    cluster = QuerySelectField(
        "Кластер", query_factory=_clusters, get_label="name",
        allow_blank=True, blank_text="— Оберіть кластер —",
        validators=[DataRequired(message="Оберіть кластер.")],
    )
    company = QuerySelectField(
        "Підприємство", query_factory=_companies, get_label="name",
        allow_blank=True, blank_text="— Оберіть підприємство —",
        validators=[DataRequired(message="Оберіть підприємство.")],
    )
    area = DecimalField(
        "Фізична площа у сезоні, га", places=2,
        validators=[DataRequired(message="Вкажіть площу."), NumberRange(min=Decimal("0.01"))],
    )
    submit = SubmitField("Зберегти сезон")


class PlantingForm(FlaskForm):
    culture = QuerySelectField(
        "Культура", query_factory=_cultures, get_label="name",
        allow_blank=True, blank_text="— Оберіть культуру —",
        validators=[DataRequired(message="Оберіть культуру.")],
    )
    area = DecimalField(
        "Посівна площа, га", places=2,
        validators=[DataRequired(message="Вкажіть площу."), NumberRange(min=Decimal("0.01"))],
    )
    note = StringField("Примітка", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Зберегти посів")


class FieldFilterForm(FlaskForm):
    class Meta:
        csrf = False  # Read-only GET filters must not put CSRF tokens in URLs.

    cluster = QuerySelectField("Кластер", query_factory=_clusters, get_label="name", allow_blank=True)
    company = QuerySelectField("Підприємство", query_factory=_companies, get_label="name", allow_blank=True)
    culture = QuerySelectField("Культура", query_factory=_cultures, get_label="name", allow_blank=True)
    submit = SubmitField("Фільтрувати")


class SeasonCreateForm(FlaskForm):
    year = IntegerField("Рік урожаю", validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    submit = SubmitField("Створити сезон")


class ActionForm(FlaskForm):
    """CSRF-protected form for seasonal copy, closing and archiving."""
