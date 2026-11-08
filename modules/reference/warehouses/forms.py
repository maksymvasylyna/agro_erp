"""Warehouse master-data forms with company lookup from the company directory."""
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.companies.models import Company
from modules.reference.shared_crud import normalize_reference_name


class WarehouseForm(FlaskForm):
    company = QuerySelectField(
        "Підприємство",
        query_factory=lambda: Company.query.order_by(Company.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть підприємство —",
        validators=[DataRequired(message="Оберіть підприємство.")],
    )
    name = StringField(
        "Назва складу",
        filters=[normalize_reference_name],
        validators=[DataRequired(message="Вкажіть назву складу."), Length(max=255)],
    )
    address = StringField(
        "Адреса / примітка",
        filters=[normalize_reference_name],
        validators=[Optional(), Length(max=255)],
    )
    is_active = BooleanField("Активний", default=True)
    submit = SubmitField("Зберегти")


class WarehouseActionForm(FlaskForm):
    """CSRF token for activating and deactivating warehouse records."""
