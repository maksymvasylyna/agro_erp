"""Seasonal data owned by the field reference directory.

Field.id remains the permanent identity. Each year has an independent
field affiliation and physical area, with one or more crop allocations.
"""
from datetime import datetime
from decimal import Decimal
from extensions import db


class Season(db.Model):
    __tablename__ = "seasons"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True, index=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("FALSE"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    fields = db.relationship("FieldSeason", back_populates="season", lazy="selectin")


class FieldSeason(db.Model):
    __tablename__ = "field_seasons"

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey("clusters.id", ondelete="RESTRICT"), nullable=False, index=True)
    area = db.Column(db.Numeric(12, 2), nullable=False)

    season = db.relationship("Season", back_populates="fields")
    field = db.relationship("Field", backref="season_records")
    company = db.relationship("Company")
    cluster = db.relationship("Cluster")
    plantings = db.relationship("FieldPlanting", back_populates="field_season",
                                cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        db.UniqueConstraint("season_id", "field_id", name="uq_field_seasons_year_field"),
        db.CheckConstraint("area > 0", name="ck_field_seasons_positive_area"),
    )

    @property
    def planted_area(self):
        return sum((p.area for p in self.plantings), Decimal("0.00"))

    @property
    def unallocated_area(self):
        return self.area - self.planted_area


class FieldPlanting(db.Model):
    __tablename__ = "field_plantings"

    id = db.Column(db.Integer, primary_key=True)
    field_season_id = db.Column(db.Integer, db.ForeignKey("field_seasons.id", ondelete="CASCADE"), nullable=False, index=True)
    culture_id = db.Column(db.Integer, db.ForeignKey("cultures.id", ondelete="RESTRICT"), nullable=False, index=True)
    area = db.Column(db.Numeric(12, 2), nullable=False)
    note = db.Column(db.String(255), nullable=True)

    field_season = db.relationship("FieldSeason", back_populates="plantings")
    culture = db.relationship("Culture")

    __table_args__ = (db.CheckConstraint("area > 0", name="ck_field_plantings_positive_area"),)
