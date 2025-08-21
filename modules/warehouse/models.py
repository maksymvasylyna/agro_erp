from extensions import db
from datetime import datetime

class StockTransaction(db.Model):
    __tablename__ = "stock_transactions"

    id = db.Column(db.Integer, primary_key=True)

    # Базове
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    qty = db.Column(db.Float, nullable=False)          # + = IN
    tx_type = db.Column(db.String(10), nullable=False, default="IN")
    tx_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    warehouse_id = db.Column(db.Integer, nullable=False, default=1)

    # Джерело
    source_kind = db.Column(db.String(50))             # 'payment_inbox'
    source_id = db.Column(db.Integer)                  # PaymentInbox.id
    source_line_idx = db.Column(db.Integer)            # № позиції в заявці (1..N)

    # Знімок довідкової інформації (для журналу/аудиту)
    product_name = db.Column(db.String(255))
    unit_text = db.Column(db.String(64))
    consumer_company_name = db.Column(db.String(255))
    payer_name = db.Column(db.String(255))
    package_text = db.Column(db.String(255))
    manufacturer_name = db.Column(db.String(255))

    note = db.Column(db.String(255))
