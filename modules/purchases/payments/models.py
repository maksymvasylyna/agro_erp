from datetime import datetime
from extensions import db

class PaymentInbox(db.Model):
    """
    Мінімальна модель «вхідної заявки в Проплати».
    Нічого зайвого: компанія, статус і набір рядків у JSON.
    """
    __tablename__ = "payment_inbox"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="submitted", index=True)

    # Формат items_json: [{"product_id": 1, "product_name": "...", "culture_name": "—", "qty": 12.3}, ...]
    items_json = db.Column(db.JSON, nullable=False, default=list)

    # Зручно мати company для відображення назви
    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return f"<PaymentInbox id={self.id} company_id={self.company_id} status={self.status}>"
