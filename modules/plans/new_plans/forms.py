from flask_wtf import FlaskForm
from wtforms import SelectField, FloatField, StringField, FieldList, FormField, SubmitField
from wtforms.validators import DataRequired

class TreatmentForm(FlaskForm):
    class Meta:
        csrf = False  # вимикаємо CSRF для вкладеної форми

    treatment_type_id = SelectField('Вид обробітку', coerce=int, validators=[DataRequired()])
    product_id = SelectField('Продукт', coerce=int, validators=[DataRequired()])
    rate = FloatField('Норма', validators=[DataRequired()])
    unit = StringField('Одиниця')
    manufacturer = StringField('Виробник')
    quantity = FloatField('Кількість')

class PlanForm(FlaskForm):
    treatments = FieldList(FormField(TreatmentForm), min_entries=1)
    submit = SubmitField('Зберегти')
