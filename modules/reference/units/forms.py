from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

class UnitForm(FlaskForm):
    name = StringField("Назва одиниці виміру", validators=[DataRequired()])
    submit = SubmitField("Зберегти")
