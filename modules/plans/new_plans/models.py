from extensions import db
from sqlalchemy.orm import relationship


class Field(db.Model):
    __tablename__ = 'fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    area = db.Column(db.Float, nullable=False)
    culture_id = db.Column(db.Integer, db.ForeignKey('cultures.id'))
    culture = relationship("Culture", backref="fields")

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class TreatmentType(db.Model):
    __tablename__ = 'treatment_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)  # 🔽 додаємо ось це поле
    ...
