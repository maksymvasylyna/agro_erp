# modules/requests/shipments/forms.py
from flask_wtf import FlaskForm
from wtforms import SubmitField
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.companies.models import Company
from modules.reference.products.models import Product
from extensions import db

def companies_query():
    return db.session.query(Company).order_by(Company.name.asc())

def products_query():
    return db.session.query(Product).order_by(Product.name.asc())

class FilterForm(FlaskForm):
    company = QuerySelectField(
        "Підприємство (споживач)",
        query_factory=companies_query,
        allow_blank=True,
        get_label="name"
    )
    product = QuerySelectField(
        "Продукт",
        query_factory=products_query,
        allow_blank=True,
        get_label="name"
    )
    submit = SubmitField("Фільтрувати")
