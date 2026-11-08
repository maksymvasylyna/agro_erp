from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from modules.reference.shared_crud import normalize_reference_name


class UnitForm(FlaskForm):
    name = StringField(
        "Назва одиниці виміру",
        filters=[normalize_reference_name],
        validators=[DataRequired(message="Заповніть назву."), Length(max=100)],
    )
    submit = SubmitField("Зберегти")


class UnitDeleteForm(FlaskForm):
    """Validates CSRF for directory deletion."""
