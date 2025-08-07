# modules/reference/payers/models.py
from extensions import db

class Payer(db.Model):
    __tablename__ = 'payers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)

    def __repr__(self):
        return f"<Payer {self.name}>"
