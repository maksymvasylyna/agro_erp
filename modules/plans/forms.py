from flask_wtf import FlaskForm
from wtforms import SelectField, FloatField, StringField, FieldList, FormField, SubmitField
from wtforms.validators import DataRequired, Optional

class TreatmentForm(FlaskForm):
    treatment_type_id = SelectField('Вид обробітку', coerce=int, validators=[DataRequired()])
    product_id = SelectField('Продукт', coerce=int, validators=[DataRequired()])
    rate = FloatField('Норма', validators=[Optional()])

    unit = StringField('Одиниця', validators=[Optional()])
    manufacturer = StringField('Виробник', validators=[Optional()])
    quantity = FloatField('Кількість', validators=[Optional()])

    class Meta:
        csrf = False


class PlanForm(FlaskForm):
    treatments = FieldList(FormField(TreatmentForm), min_entries=0)
    submit = SubmitField('Зберегти план')