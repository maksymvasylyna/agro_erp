from flask_wtf import FlaskForm
from wtforms import SelectField, FloatField, StringField, FieldList, FormField, SubmitField
from wtforms.validators import DataRequired

class TreatmentForm(FlaskForm):
    treatment_type_id = SelectField('Вид обробітку', coerce=int, validators=[DataRequired()])
    product_id = SelectField('Продукт', coerce=int, validators=[DataRequired()])
    rate = FloatField('Норма', validators=[DataRequired()])
    unit = StringField('Одиниця')         # readonly в шаблоні
    manufacturer = StringField('Виробник') # readonly в шаблоні
    quantity = FloatField('Кількість')     # розраховується

    class Meta:
        csrf = False  # ✅ Вимикаємо CSRF для підформи

class PlanForm(FlaskForm):
    treatments = FieldList(FormField(TreatmentForm), min_entries=0)
    submit = SubmitField('Зберегти план')
