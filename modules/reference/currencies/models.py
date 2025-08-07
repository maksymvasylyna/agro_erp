# modules/reference/submodules/currencies/models.py
from extensions import db

class Currency(db.Model):
    __tablename__ = 'currencies'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Currency {self.code}>"
