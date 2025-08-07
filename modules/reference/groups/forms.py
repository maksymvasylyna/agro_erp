from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

class GroupForm(FlaskForm):
    name = StringField("Назва", validators=[DataRequired()])
    submit = SubmitField("Зберегти")