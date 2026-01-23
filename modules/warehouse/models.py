from datetime import datetime
from extensions import db
from sqlalchemy import Index, CheckConstraint
from sqlalchemy.orm import relationship
from modules.reference.products.models import Product
from modules.reference.units.models import Unit
from modules.reference.companies.models import Company
from modules.reference.payers.models import Payer
from modules.reference.manufacturers.models import Manufacturer


class StockTransaction(db.Model):
    __tablename__ = "stock_transactions"

    id = db.Column(db.Integer, primary_key=True)

    # відповідно до існуючої таблиці
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    unit_id    = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    qty        = db.Column(db.Float, nullable=False)                  # ≥ 0
    tx_type    = db.Column(db.String(10), nullable=False)             # 'IN' / 'OUT'
    tx_date    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    note            = db.Column(db.String(255), nullable=True)
    source_kind     = db.Column(db.String(50), nullable=True)
    source_id       = db.Column(db.Integer, nullable=True)
    warehouse_id    = db.Column(db.Integer, nullable=False)
    source_line_idx = db.Column(db.Integer, nullable=True)

    # текстові снапшоти (вже існують у БД)
    product_name           = db.Column(db.Text, nullable=True)
    unit_text              = db.Column(db.Text, nullable=True)
    consumer_company_name  = db.Column(db.Text, nullable=True)
    payer_name             = db.Column(db.Text, nullable=True)
    package_text           = db.Column(db.Text, nullable=True)
    manufacturer_name      = db.Column(db.Text, nullable=True)

    # 🔽 ДОДАНІ РАНІШЕ колонки для ключа балансу
    consumer_company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    payer_id            = db.Column(db.Integer, db.ForeignKey("payers.id"), nullable=True)
    manufacturer_id     = db.Column(db.Integer, db.ForeignKey("manufacturers.id"), nullable=True)
    package_value       = db.Column(db.Float, nullable=True)

    # зв'язки (для зручних join/виводу)
    product          = relationship(Product, lazy="joined")
    unit             = relationship(Unit, lazy="joined")
    consumer_company = relationship(Company, lazy="joined")
    payer            = relationship(Payer, lazy="joined")
    manufacturer     = relationship(Manufacturer, lazy="joined")

    __table_args__ = (
        Index("ix_st_tx_product", "product_id"),
        Index("ix_st_tx_company", "consumer_company_id"),
        Index("ix_st_tx_payer", "payer_id"),
        Index("ix_st_tx_unit", "unit_id"),
        Index("ix_st_tx_manufacturer", "manufacturer_id"),
        Index("ix_st_tx_balance_key",
              "consumer_company_id", "product_id", "payer_id",
              "unit_id", "manufacturer_id", "package_value"),
        CheckConstraint("qty >= 0", name="ck_st_tx_qty_nonneg"),
        CheckConstraint("tx_type in ('IN','OUT')", name="ck_st_tx_type"),
    )
