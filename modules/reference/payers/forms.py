"""Validated payment-payer directory forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length

from modules.reference.shared_crud import normalize_reference_name


class PayerForm(FlaskForm):
    name = StringField(
        "Назва платника",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву платника."),
            Length(max=128, message="Назва платника не може перевищувати 128 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class PayerDeleteForm(FlaskForm):
    """CSRF-protected deletion only for unreferenced payers."""
