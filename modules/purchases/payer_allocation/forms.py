# modules/purchases/payer_allocation/forms.py
from flask_wtf import FlaskForm
from wtforms import SubmitField, SelectMultipleField, HiddenField
from wtforms_sqlalchemy.fields import QuerySelectField
from modules.reference.companies.models import Company
from modules.reference.manufacturers.models import Manufacturer
from modules.reference.products.models import Product
from modules.reference.payers.models import Payer

def companies_q(): return Company.query.order_by(Company.name).all()
def manufacturers_q(): return Manufacturer.query.order_by(Manufacturer.name).all()
def products_q(): return Product.query.order_by(Product.name).all()
def payers_q(): return Payer.query.order_by(Payer.name).all()

class AllocationFilterForm(FlaskForm):
    company = QuerySelectField("Підприємство", query_factory=companies_q, get_label="name", allow_blank=True, blank_text="— Усі —")
    product = QuerySelectField("Продукт", query_factory=products_q, get_label="name", allow_blank=True, blank_text="— Усі —")
    manufacturer = QuerySelectField("Виробник", query_factory=manufacturers_q, get_label="name", allow_blank=True, blank_text="— Усі —")
    payer = QuerySelectField("Платник", query_factory=payers_q, get_label="name", allow_blank=True, blank_text="— Усі —")
    submit = SubmitField("Фільтрувати")

class BulkAssignForm(FlaskForm):
    payer = QuerySelectField("Платник", query_factory=payers_q, get_label="name", allow_blank=False)
    ids = HiddenField("ids")  # список id через кому
    assign = SubmitField("Застосувати")
