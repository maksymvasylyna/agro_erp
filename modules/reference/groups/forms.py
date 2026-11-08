"""Validated group directory forms, shared with product selection."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length

from modules.reference.shared_crud import normalize_reference_name


class GroupForm(FlaskForm):
    name = StringField(
        "Назва групи продуктів",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву групи продуктів."),
            Length(max=128, message="Назва групи не може перевищувати 128 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class GroupDeleteForm(FlaskForm):
    """Protect POST deletion with CSRF."""
