"""Forms and input validation for the product-category directory."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length

from modules.reference.shared_crud import normalize_reference_name


class CategoryForm(FlaskForm):
    name = StringField(
        "Назва категорії",
        filters=[normalize_reference_name],
        validators=[
            DataRequired(message="Вкажіть назву категорії."),
            Length(max=100, message="Назва не може перевищувати 100 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class CategoryDeleteForm(FlaskForm):
    """CSRF-protected deletion of an unused category."""
