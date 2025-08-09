# modules/plans/models.py

from extensions import db
from datetime import datetime


class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String, default='готовий')
    is_approved = db.Column(db.Boolean, default=False)

    field = db.relationship('Field', backref='plans')
    treatments = db.relationship('Treatment', backref='plan', cascade='all, delete-orphan')


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

    treatment_type = db.relationship('TreatmentType', backref='treatments')
    product = db.relationship('Product', backref='treatments')
