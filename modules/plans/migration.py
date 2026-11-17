"""Idempotent PostgreSQL upgrade for season-bound plans.

One-time legacy cleanup requires a deliberately set Render flag and a count
guard. It never touches fields, seasons, cultures, products or other modules.
Public source code contains no production field data or credentials.
"""
import os
from sqlalchemy import text
from extensions import db

RESET_FLAG = "AGROERP_CLEAR_LEGACY_PLANS_ONCE"
RESET_VALUE = "CLEAR_26_PLANS_306_TREATMENTS_2026_11_17"
MIGRATION_KEY = "plans_seasons_initial_cleanup_2026_11_17"


def ensure_schema():
    if db.engine.dialect.name != "postgresql":
        return
    with db.engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(381525, 20261117)"))
        exists = conn.execute(
            text("SELECT to_regclass('public.plans') IS NOT NULL")
        ).scalar_one()
        if not exists:
            return

        conn.execute(text("ALTER TABLE public.plans ADD COLUMN IF NOT EXISTS season_id integer"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_plans_season_id ON public.plans (season_id)"))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                  SELECT 1 FROM pg_constraint
                  WHERE conname = 'fk_plans_season_id'
                    AND conrelid = 'public.plans'::regclass
                ) THEN
                  ALTER TABLE public.plans ADD CONSTRAINT fk_plans_season_id
                  FOREIGN KEY (season_id) REFERENCES public.seasons(id)
                  ON DELETE RESTRICT;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.agroerp_plan_maintenance (
                operation_key text PRIMARY KEY,
                executed_at timestamptz NOT NULL DEFAULT current_timestamp,
                deleted_plans integer NOT NULL,
                deleted_treatments integer NOT NULL,
                deleted_plan_treatments integer NOT NULL
            )
        """))

        if os.getenv(RESET_FLAG) == RESET_VALUE:
            logged = conn.execute(text(
                "SELECT EXISTS(SELECT 1 FROM public.agroerp_plan_maintenance "
                "WHERE operation_key=:key)"
            ), {"key": MIGRATION_KEY}).scalar_one()
            if not logged:
                plans = conn.execute(text("SELECT count(*) FROM public.plans")).scalar_one()
                legacy = conn.execute(text(
                    "SELECT count(*) FROM public.plans WHERE season_id IS NULL "
                    "AND status = 'готовий' AND is_approved IS FALSE"
                )).scalar_one()
                treatments = conn.execute(text("SELECT count(*) FROM public.treatments")).scalar_one()
                plan_treatments = conn.execute(text(
                    "SELECT count(*) FROM public.plan_treatments"
                )).scalar_one()
                # Never erase later valid plans, or unexpected new rows.
                if (plans, legacy, treatments, plan_treatments) != (26, 26, 306, 0):
                    raise RuntimeError(
                        "Plan cleanup aborted: expected exactly 26 old plans, "
                        "306 treatments, 0 plan_treatments, and no season plans; "
                        f"actual counts: {(plans, legacy, treatments, plan_treatments)}"
                    )
                conn.execute(text(
                    "TRUNCATE TABLE public.plan_treatments, public.treatments, "
                    "public.plans RESTART IDENTITY"
                ))
                conn.execute(text("""
                    INSERT INTO public.agroerp_plan_maintenance
                      (operation_key, deleted_plans, deleted_treatments,
                       deleted_plan_treatments)
                    VALUES (:key, :p, :t, :pt)
                """), {"key": MIGRATION_KEY, "p": plans,
                       "t": treatments, "pt": plan_treatments})

        # The FK + required season protect all future inserts.
        null_count = conn.execute(text(
            "SELECT count(*) FROM public.plans WHERE season_id IS NULL"
        )).scalar_one()
        if null_count == 0:
            conn.execute(text("ALTER TABLE public.plans ALTER COLUMN season_id SET NOT NULL"))
