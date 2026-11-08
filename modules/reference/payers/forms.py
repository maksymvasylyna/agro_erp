from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from modules.reference.shared_crud import normalize_reference_name


class PayerForm(FlaskForm):
    name = StringField(
        "Назва платника",
        filters=[normalize_reference_name],
        validators=[DataRequired(message="Заповніть назву."), Length(max=128)],
    )
    submit = SubmitField("Зберегти")


class PayerDeleteForm(FlaskForm):
    """Validates CSRF for directory deletion."""
