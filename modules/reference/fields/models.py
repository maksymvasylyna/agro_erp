# modules/reference/fields/models.py

from extensions import db

class Field(db.Model):
    __tablename__ = 'fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)

    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    culture_id = db.Column(db.Integer, db.ForeignKey('cultures.id'))  # ✅ Прив'язка

    area = db.Column(db.Float, nullable=True)

    cluster = db.relationship('Cluster', backref='fields')
    company = db.relationship('Company', backref='fields')
    culture = db.relationship('Culture', backref='fields')  # ✅ Зв'язок ORM

    def __repr__(self):
        return f'<Field {self.name}>'
    

