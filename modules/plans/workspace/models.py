"""Technology plans attached to a specific crop allocation, not a mutable field snapshot.

These additive pilot tables intentionally do NOT overwrite legacy plans or
purchase allocations. Integrate them only after the workflow is reviewed.
"""
from datetime import datetime
from extensions import db


class TechnologyPlan(db.Model):
    __tablename__ = "technology_plans"

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id", ondelete="RESTRICT"), nullable=False, index=True)
    planting_id = db.Column(db.Integer, db.ForeignKey("field_plantings.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    status = db.Column(db.String(16), nullable=False, default="draft", server_default="draft")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    season = db.relationship("Season")
    planting = db.relationship("FieldPlanting")
    operations = db.relationship(
        "TechnologyOperation", back_populates="plan", cascade="all, delete-orphan",
        order_by="TechnologyOperation.position", lazy="selectin",
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('draft', 'ready', 'approved')", name="ck_technology_plan_status"),
    )


class TechnologyOperation(db.Model):
    __tablename__ = "technology_operations"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("technology_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    treatment_type_id = db.Column(db.Integer, db.ForeignKey("treatment_types.id", ondelete="RESTRICT"), nullable=False)
    label = db.Column(db.String(180), nullable=False, default="")
    bbch = db.Column(db.String(30))
    planned_date = db.Column(db.Date)
    basis_unit = db.Column(db.String(4), nullable=False, default="ha")
    basis_quantity = db.Column(db.Numeric(14, 3), nullable=False)
    plan = db.relationship("TechnologyPlan", back_populates="operations")
    treatment_type = db.relationship("TreatmentType")
    products = db.relationship(
        "TechnologyProduct", back_populates="operation", cascade="all, delete-orphan",
        order_by="TechnologyProduct.id", lazy="selectin",
    )

    __table_args__ = (
        db.CheckConstraint("basis_unit IN ('ha', 't')", name="ck_technology_basis_unit"),
        db.CheckConstraint("basis_quantity > 0", name="ck_technology_basis_quantity"),
    )


class TechnologyProduct(db.Model):
    __tablename__ = "technology_operation_products"

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("technology_operations.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    rate = db.Column(db.Numeric(14, 4), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_snapshot = db.Column(db.String(40), nullable=False, default="")
    operation = db.relationship("TechnologyOperation", back_populates="products")
    product = db.relationship("Product")

    __table_args__ = (
        db.CheckConstraint("rate > 0", name="ck_technology_product_rate"),
        db.CheckConstraint("quantity > 0", name="ck_technology_product_quantity"),
    )
