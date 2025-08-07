from flask_wtf import FlaskForm
from wtforms import IntegerField, SubmitField
from wtforms_sqlalchemy.fields import QuerySelectField
from wtforms.validators import Optional, NumberRange
from modules.reference.clusters.models import Cluster

class SummaryStructureFilterForm(FlaskForm):
    season_year = IntegerField(
        'Рік посіву',
        validators=[Optional(), NumberRange(min=2000, max=2100)]
    )
    cluster = QuerySelectField(
        'Кластер',
        query_factory=lambda: Cluster.query.all(),
        get_label='name',
        allow_blank=True
    )
    submit = SubmitField('Застосувати')
