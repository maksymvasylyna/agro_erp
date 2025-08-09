# modules/purchases/needs/forms.py

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import Optional

def optional_int(value):
    # Повертаємо None для порожніх значень, інакше приводимо до int
    if value in (None, '', 'None'):
        return None
    return int(value)

class NeedsFilterForm(FlaskForm):
    company_id = SelectField('Компанія', coerce=optional_int, validators=[Optional()])
    culture_id = SelectField('Культура', coerce=optional_int, validators=[Optional()])
    product_id = SelectField('Продукт',  coerce=optional_int, validators=[Optional()])
    submit = SubmitField('Фільтрувати')
