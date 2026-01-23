# modules/requests/shipments/models.py
from datetime import datetime
from extensions import db
from sqlalchemy.orm import relationship

# Імпорти довідників для relationship
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from modules.reference.companies.models import Company
from modules.reference.payers.models import Payer
from modules.reference.manufacturers.models import Manufacturer


class ShipmentRequest(db.Model):
    __tablename__ = "shipment_requests"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(32), nullable=False, unique=True)  # SR-YYYY-#### 
    status = db.Column(db.String(16), nullable=False, default="draft")  # draft/submitted/approved/executed/cancelled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(64), nullable=True)
    comment = db.Column(db.String(255), nullable=True)

    items = relationship(
        "ShipmentRequestItem",
        backref="request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<ShipmentRequest {self.number} status={self.status}>"


class ShipmentRequestItem(db.Model):
    __tablename__ = "shipment_request_items"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("shipment_requests.id"), nullable=False)

    consumer_company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    product_id          = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    payer_id            = db.Column(db.Integer, db.ForeignKey("payers.id"), nullable=True)
    unit_id             = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    manufacturer_id     = db.Column(db.Integer, db.ForeignKey("manufacturers.id"), nullable=True)
    package_value       = db.Column(db.Float, nullable=True)

    qty_requested = db.Column(db.Float, nullable=False)
    qty_executed  = db.Column(db.Float, nullable=False, default=0.0)

    # 🔽 нові снапшот-поля (fallback, якщо *_id немає)
    consumer_company_name = db.Column(db.Text, nullable=True)
    payer_name            = db.Column(db.Text, nullable=True)
    manufacturer_name     = db.Column(db.Text, nullable=True)
    unit_text             = db.Column(db.Text, nullable=True)
    package_text          = db.Column(db.Text, nullable=True)
    product_name          = db.Column(db.Text, nullable=True)

    # relationships
    product = relationship(Product, lazy="joined")
    unit = relationship(Unit, lazy="joined")
    consumer_company = relationship(Company, foreign_keys=[consumer_company_id], lazy="joined")
    payer = relationship(Payer, foreign_keys=[payer_id], lazy="joined")
    manufacturer = relationship(Manufacturer, foreign_keys=[manufacturer_id], lazy="joined")

