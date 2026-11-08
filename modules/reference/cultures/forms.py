"""Validation for the crop/culture reference directory."""
from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError

from .models import Culture


def normalize_culture_name(value):
    return " ".join((value or "").split())


class CultureForm(FlaskForm):
    name = StringField(
        "Назва культури",
        filters=[normalize_culture_name],
        validators=[
            DataRequired(message="Вкажіть назву культури."),
            Length(max=128, message="Назва культури не може перевищувати 128 символів."),
        ],
    )
    submit = SubmitField("Зберегти")

    def __init__(self, *args, **kwargs):
        self.culture_id = kwargs.pop("culture_id", None)
        super().__init__(*args, **kwargs)

    def validate_name(self, field):
        name = normalize_culture_name(field.data)
        if not name:
            return
        query = Culture.query.filter(func.lower(Culture.name) == name.lower())
        if self.culture_id is not None:
            query = query.filter(Culture.id != self.culture_id)
        if query.first() is not None:
            raise ValidationError("Культура з такою назвою вже існує.")


class CultureDeleteForm(FlaskForm):
    """CSRF-protected deletion of an unused culture."""
