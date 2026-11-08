"""Validation for the cluster reference directory."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


def normalize_cluster_name(value):
    return " ".join((value or "").split())


class ClusterForm(FlaskForm):
    name = StringField(
        "Назва кластера",
        filters=[normalize_cluster_name],
        validators=[
            DataRequired(message="Вкажіть назву кластера."),
            Length(max=128, message="Назва кластера не може перевищувати 128 символів."),
        ],
    )
    submit = SubmitField("Зберегти")


class ClusterDeleteForm(FlaskForm):
    """A CSRF-protected form for intentional deletion of unused clusters."""
