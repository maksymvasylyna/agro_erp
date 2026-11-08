"""Reusable, read-only dependency checks for master-data directories.

Introspect actual database foreign keys, including operational tables not
mapped by an ORM. No dependent rows are ever deleted automatically.
"""
from functools import lru_cache

from sqlalchemy import Column, Integer, MetaData, Table, func, inspect, select
from extensions import db


@lru_cache(maxsize=64)
def _foreign_keys_for(engine, target):
    inspector = inspect(engine)
    items = []
    for table_name in inspector.get_table_names():
        for constraint in inspector.get_foreign_keys(table_name):
            if constraint.get("referred_table") == target:
                for column in constraint.get("constrained_columns", ()):
                    items.append((table_name, column))
    return tuple(items)


def linked_record_counts(model):
    """Return {parent_id: total referencing rows}, grouped across all FKs."""
    linked = {}
    for table_name, field_name in _foreign_keys_for(db.engine, model.__tablename__):
        table = Table(table_name, MetaData(), Column(field_name, Integer))
        field = table.c[field_name]
        stmt = (
            select(field, func.count())
            .select_from(table)
            .where(field.is_not(None))
            .group_by(field)
        )
        for parent_id, count in db.session.execute(stmt):
            linked[parent_id] = linked.get(parent_id, 0) + count
    return linked


def normalize_reference_name(value):
    return " ".join((value or "").split())
