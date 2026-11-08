from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from modules.reference.shared_crud import normalize_reference_name


class ManufacturerForm(FlaskForm):
    name = StringField(
        "Назва виробника",
        filters=[normalize_reference_name],
        validators=[DataRequired(message="Заповніть назву."), Length(max=128)],
    )
    submit = SubmitField("Зберегти")


class ManufacturerDeleteForm(FlaskForm):
    """Validates CSRF for directory deletion."""
