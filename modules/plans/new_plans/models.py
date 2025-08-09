from extensions import db
from sqlalchemy.orm import relationship

from modules.reference.fields.field_models import Field
from modules.reference.products.models import Product
from modules.reference.treatment_types.models import TreatmentType


class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)

    # зв'язки
    field = relationship('Field', backref='plans')
    treatments = relationship('Treatment', backref='plan', cascade='all, delete-orphan')


class Treatment(db.Model):
    __tablename__ = 'treatments'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)

    treatment_type_id = db.Column(db.Integer, db.ForeignKey('treatment_types.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    rate = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String)
    manufacturer = db.Column(db.String)
    quantity = db.Column(db.Float)

    # зв'язки
    treatment_type = relationship('TreatmentType', backref='treatments')
    product = relationship('Product', backref='treatments')
