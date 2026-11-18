"""Canonical product records, chemistry and verified registration metadata."""

from extensions import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"))
    manufacturer_id = db.Column(db.Integer, db.ForeignKey("manufacturers.id"))
    container = db.Column(db.String(100), nullable=True)

    # Nullable additive fields are migrated for historical production records.
    formulation_code = db.Column(db.String(32), nullable=True)
    formulation_name = db.Column(db.String(160), nullable=True)
    composition = db.Column(db.Text, nullable=True)
    registration_status = db.Column(db.String(80), nullable=True)
    registration_number = db.Column(db.String(120), nullable=True)
    registration_valid_until = db.Column(db.Date, nullable=True)
    source_url = db.Column(db.Text, nullable=True)
    source_note = db.Column(db.Text, nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, server_default="false")

    category = db.relationship("Category", backref="products")
    unit = db.relationship("Unit", backref="products")
    group = db.relationship("Group", backref="products")
    manufacturer = db.relationship("Manufacturer", backref="products")
    components = db.relationship(
        "ProductIngredient", back_populates="product",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Product {self.name}>"


class ActiveIngredient(db.Model):
    """Reusable substances, not product-specific concentration records."""
    __tablename__ = "active_ingredients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    chemical_group = db.Column(db.String(150), nullable=True)
    frac_group = db.Column(db.String(50), nullable=True)
    irac_group = db.Column(db.String(50), nullable=True)
    hrac_group = db.Column(db.String(50), nullable=True)


class ProductIngredient(db.Model):
    """One row per substance/component and concentration in a product."""
    __tablename__ = "product_ingredients"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ingredient_id = db.Column(
        db.Integer, db.ForeignKey("active_ingredients.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    concentration_value = db.Column(db.Float, nullable=True)
    concentration_unit = db.Column(db.String(30), nullable=True)
    is_safener = db.Column(db.Boolean, nullable=False, default=False)
    product = db.relationship("Product", back_populates="components")
    ingredient = db.relationship("ActiveIngredient")
