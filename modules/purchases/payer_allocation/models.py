# modules/purchases/payer_allocation/models.py
from datetime import datetime
from extensions import db

class PayerAllocation(db.Model):
    """
    Снапшот потреби з планів на зерні (field, product) + призначений платник.
    qty оновлюється при синхронізації з планів; payer_id зберігається.
    """
    __tablename__ = "payer_allocations"

    id = db.Column(db.Integer, primary_key=True)

    # Зв'язки
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    manufacturer_id = db.Column(db.Integer, db.ForeignKey("manufacturers.id"), nullable=True, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)

    # Дані
    qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    payer_id = db.Column(db.Integer, db.ForeignKey("payers.id"), nullable=True, index=True)

    # Стан / аудит
    status = db.Column(db.String(16), nullable=False, default="active", index=True)  # active | stale
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    assigned_at = db.Column(db.DateTime, nullable=True)

    # Унікальність одного продукту на полі
    __table_args__ = (
        db.UniqueConstraint("field_id", "product_id", name="uq_alloc_field_product"),
    )

    # ORM відносини (для зручності в шаблонах/фільтрах)
    field = db.relationship("Field")
    company = db.relationship("Company")
    product = db.relationship("Product")
    manufacturer = db.relationship("Manufacturer")
    unit = db.relationship("Unit")
    payer = db.relationship("Payer")
