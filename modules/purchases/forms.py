# modules/purchases/needs/forms.py

from flask_wtf import FlaskForm
from wtforms import SubmitField
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.products.models import Product

class NeedsFilterForm(FlaskForm):
    company = QuerySelectField("Компанія", query_factory=lambda: Company.query.order_by(Company.name).all(), allow_blank=True, get_label='name')
    culture = QuerySelectField("Культура", query_factory=lambda: Culture.query.order_by(Culture.name).all(), allow_blank=True, get_label='name')
    product = QuerySelectField("Продукт", query_factory=lambda: Product.query.order_by(Product.name).all(), allow_blank=True, get_label='name')
    submit = SubmitField("🔍 Показати")
