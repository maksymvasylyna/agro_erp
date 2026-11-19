"""Audit or explicitly apply the one-plan-per-field-per-season constraint.

DEFAULT: read-only audit. No automatic execution from the Flask app.
Do not use --apply until production PostgreSQL has an independently verified
pg_dump backup AND a tested restore, in an approved maintenance window.
"""
import argparse
import os
from sqlalchemy import create_engine, text
from config import Config

GUARD = "BACKUP_AND_RESTORE_VERIFIED_FOR_AGROERP_PLANS_2026_11_19"
CHECK = text("""
    SELECT season_id, field_id, COUNT(*) AS count
    FROM public.plans
    GROUP BY season_id, field_id
    HAVING COUNT(*) > 1
    ORDER BY count DESC
    LIMIT 25
""")
CONSTRAINT = text("""
    SELECT COUNT(*) FROM pg_constraint
    WHERE conrelid = 'public.plans'::regclass
    AND conname = 'uq_plans_season_field'
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Explicit write: requires verified DB backup and environment guard")
    args = parser.parse_args()
    if args.apply and os.environ.get("AGROERP_PLANS_UNIQUE_MIGRATION") != GUARD:
        parser.error("Refusing schema change: backup/restore confirmation is missing.")
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    if engine.dialect.name != "postgresql":
        parser.error("This migration is only for PostgreSQL.")
    with engine.begin() as conn:
        duplicates = conn.execute(CHECK).mappings().all()
        missing = conn.execute(
            text("SELECT COUNT(*) FROM public.plans WHERE season_id IS NULL")
        ).scalar_one()
        exists = bool(conn.execute(CONSTRAINT).scalar_one())
        print(f"Duplicate (season, field) groups: {len(duplicates)}; "
              f"plans without a season: {missing}; constraint exists: {exists}")
        for row in duplicates:
            print(dict(row))
        if duplicates or missing:
            raise SystemExit("Failed preflight; no changes made.")
        if not args.apply:
            print("READ-ONLY AUDIT. No schema change made.")
            return
        # Lock and recheck in the same transaction to prevent races with writes.
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text("LOCK TABLE public.plans IN SHARE ROW EXCLUSIVE MODE"))
        if conn.execute(CHECK).first() or conn.execute(
            text("SELECT COUNT(*) FROM public.plans WHERE season_id IS NULL")
        ).scalar_one():
            raise SystemExit("Concurrent change detected, migration aborted.")
        if not conn.execute(CONSTRAINT).scalar_one():
            conn.execute(text("""
                ALTER TABLE public.plans
                ADD CONSTRAINT uq_plans_season_field UNIQUE (season_id, field_id)
            """))
            print("Constraint installed.")
        else:
            print("Constraint already installed.")


if __name__ == "__main__":
    main()
