# -*- coding: utf-8 -*-
"""
Довідник складів підприємств (одержувачів).
Використовується у заявках на відвантаження як "склад-одержувач".
"""

from __future__ import annotations
from datetime import datetime
from extensions import db


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)

    # Підприємство-власник (споживач), до якого належить склад
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)

    # Назва складу в межах компанії (унікальна в парі company_id + name)
    name = db.Column(db.String(255), nullable=False)

    # Необов'язково: адреса/опис
    address = db.Column(db.String(255), nullable=True)

    # Активність для фільтрації у випадаючих списках
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    # Аудитні поля
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("company_id", "name", name="uq_warehouses_company_name"),
    )

    # Зв'язки
    company = db.relationship(
        "Company",
        backref=db.backref("warehouses", lazy="dynamic"),
        foreign_keys=[company_id],
    )

    # ── Утиліти ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Warehouse id={self.id} company_id={self.company_id} name={self.name!r}>"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "address": self.address,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def active_for_company(cls, company_id: int):
        """Повертає query активних складів конкретної компанії (для select у формах)."""
        return cls.query.filter(cls.company_id == company_id, cls.is_active.is_(True)).order_by(cls.name.asc())
