
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

class CurrencyForm(FlaskForm):
    code = StringField('Код', validators=[DataRequired()])
    name = StringField('Назва', validators=[DataRequired()])
    submit = SubmitField('Зберегти')
