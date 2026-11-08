"""Validated manufacturer directory forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length

from modules.reference.shared_crud import normalize_reference_name


class ManufacturerForm(FlaskForm):
    name = StringField(
        "Назва виробника",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву виробника."),
            Length(max=128, message="Назва виробника не може перевищувати 128 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class ManufacturerDeleteForm(FlaskForm):
    """CSRF protection for deletion of unused manufacturers."""
