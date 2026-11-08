"""Validated currency directory forms; preserve legacy $ and € codes."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError

from modules.reference.shared_crud import normalize_reference_name


def normalize_currency_code(value):
    return (value or "").strip().upper()


class CurrencyForm(FlaskForm):
    code = StringField(
        "Код або символ валюти",
        filters=[normalize_currency_code],
        validators=[
            DataRequired(message="Вкажіть код або символ валюти."),
            Length(max=10, message="Код валюти не може перевищувати 10 символів."),
        ],
    )
    name = StringField(
        "Назва валюти",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву валюти."),
            Length(max=100, message="Назва не може перевищувати 100 символів."),
        ],
    )
    submit = SubmitField("Зберегти")

    def validate_code(self, field):
        if field.data and any(character.isspace() for character in field.data):
            raise ValidationError("Код або символ валюти не може містити пробілів.")


class CurrencyDeleteForm(FlaskForm):
    """CSRF-protected currency deletion."""
