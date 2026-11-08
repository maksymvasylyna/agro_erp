"""Validated forms for the types-of-treatment master directory."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length

from modules.reference.shared_crud import normalize_reference_name


class TreatmentTypeForm(FlaskForm):
    name = StringField(
        "Назва виду обробітку",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву виду обробітку."),
            Length(max=100, message="Назва не може перевищувати 100 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class TreatmentTypeDeleteForm(FlaskForm):
    """CSRF-protected deletion of a treatment type with no dependencies."""
