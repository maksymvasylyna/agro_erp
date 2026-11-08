"""Company reference forms: keep companies linked to valid clusters."""
from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError
from wtforms_sqlalchemy.fields import QuerySelectField

from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company


def normalize_company_name(value):
    return " ".join((value or "").split())


def cluster_query():
    return Cluster.query.order_by(Cluster.name).all()


class CompanyForm(FlaskForm):
    name = StringField(
        "Назва підприємства",
        filters=[normalize_company_name],
        validators=[
            DataRequired(message="Вкажіть назву підприємства."),
            Length(max=100, message="Назва не може перевищувати 100 символів."),
        ],
    )
    cluster = QuerySelectField(
        "Кластер",
        query_factory=cluster_query,
        get_label="name",
        allow_blank=True,
        blank_text="— Оберіть кластер —",
        validators=[DataRequired(message="Оберіть кластер для підприємства.")],
    )
    submit = SubmitField("Зберегти")

    def __init__(self, *args, **kwargs):
        self.obj_id = kwargs.pop("obj_id", None)
        super().__init__(*args, **kwargs)

    def validate_name(self, field):
        name = normalize_company_name(field.data)
        if not name:
            return
        query = Company.query.filter(func.lower(Company.name) == name.lower())
        if self.obj_id is not None:
            query = query.filter(Company.id != self.obj_id)
        if query.first() is not None:
            raise ValidationError("Підприємство з такою назвою вже існує.")


class CompanyFilterForm(FlaskForm):
    name = QuerySelectField(
        "Підприємство",
        query_factory=lambda: Company.query.order_by(Company.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text="— Усі підприємства —",
    )
    cluster = QuerySelectField(
        "Кластер",
        query_factory=cluster_query,
        get_label="name",
        allow_blank=True,
        blank_text="— Усі кластери —",
    )
    submit = SubmitField("Фільтрувати")


class CompanyDeleteForm(FlaskForm):
    """Flask-WTF CSRF validation for deleting a company with no dependencies."""
