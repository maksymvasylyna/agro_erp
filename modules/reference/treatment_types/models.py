from extensions import db

class TreatmentType(db.Model):
    __tablename__ = 'treatment_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
