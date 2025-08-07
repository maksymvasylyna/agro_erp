# modules/reference/products/models.py

from extensions import db

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)

    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'))
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'))
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturers.id'))

    container = db.Column(db.String(100), nullable=True)

    category = db.relationship('Category', backref='products')
    unit = db.relationship('Unit', backref='products')
    group = db.relationship('Group', backref='products')
    manufacturer = db.relationship('Manufacturer', backref='products')

    def __repr__(self):
        return f'<Product {self.name}>'
