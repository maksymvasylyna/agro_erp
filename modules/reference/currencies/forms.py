from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from modules.reference.shared_crud import normalize_reference_name


def normalize_currency_code(value):
    return normalize_reference_name(value).upper()


class CurrencyForm(FlaskForm):
    code = StringField(
        "Код валюти", filters=[normalize_currency_code],
        validators=[DataRequired(message="Вкажіть код."), Length(max=10)],
    )
    name = StringField(
        "Назва валюти", filters=[normalize_reference_name],
        validators=[DataRequired(message="Вкажіть назву."), Length(max=100)],
    )
    submit = SubmitField("Зберегти")


class CurrencyDeleteForm(FlaskForm):
    """CSRF-protected delete form."""
