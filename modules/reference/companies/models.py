from extensions import db
from modules.reference.clusters.models import Cluster

class Company(db.Model):
    __tablename__ = 'companies'  # не обов’язково, але бажано для стабільності

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'), nullable=False)

    cluster = db.relationship('Cluster', backref='companies')
