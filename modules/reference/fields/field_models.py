# modules/reference/fields/models.py

from extensions import db
from sqlalchemy import text

class Field(db.Model):
    __tablename__ = 'fields'

    id = db.Column(db.Integer, primary_key=True)

    # ВАЖЛИВО: прибрали global unique, бо унікальність тепер забезпечує
    # частковий індекс у БД лише серед активних записів.
    name = db.Column(db.String(255), nullable=False)

    # Прапорець архівації (має відповідати колонці, яку ми додали в БД)
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        server_default=text('TRUE'),
        default=True,
    )

    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    culture_id = db.Column(db.Integer, db.ForeignKey('cultures.id'))

    area = db.Column(db.Float, nullable=True)

    cluster = db.relationship('Cluster', backref='fields')
    company = db.relationship('Company', backref='fields')
    culture = db.relationship('Culture', backref='fields')

    def __repr__(self):
        return f"<Field id={self.id} name='{self.name}'>"
