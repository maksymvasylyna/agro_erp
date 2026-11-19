# AgroERP — existing planning workflow, hardening stage 1

Date: 2026-11-19
Branch: `feature/planning-hardening-phase1-2026-11-19`
Base: `main` (old familiar UI, no planning workspace pilot).

## Preserved business workflow

Plans → Нові плани → Створити план по полю → cluster → company →
field without a plan → treatments and products.
Alternative bulk-template creation is also retained.
One field = one crop = one plan within one selected harvest season.
The new technology-planning pilot is NOT merged.

## Changes in this branch

- Admin is now required for approval, bulk approval, delete, and unlock.
  Existing creation/editing remains open pending a proper role model.
- All sensitive status changes are POST with CSRF and posted-season checks.
  GET approval and unlock URLs are rejected.
- Closed seasons reject status changes and deletions.
- Approved plans cannot be edited or deleted directly.
- New plans require exactly one crop allocation in the current season.
- Per-field row locks serialize concurrent create attempts on PostgreSQL.
  The model declares a unique constraint on (season_id, field_id).
- Rate, material quantity, unit and manufacturer are verified/derived on
  the server for create, edit, and bulk create (browser values are ignored).
- Admin login no longer resets the selected harvest season.
- Automated SQLite tests cover seasonal isolation, authorization, statuses,
  tampered quantities, duplicate plans, and real CSRF enforcement.

## Database migration is intentionally NOT automatic

`db.create_all()` does NOT install a newly added constraint on an existing
PostgreSQL table. Never interpret the ORM declaration as a completed production
migration.

A read-only production SQL check on 2026-11-19 returned **zero** duplicate
(season_id, field_id) groups. The constraint was **NOT** installed on production.

First obtain an **independent verified `pg_dump -Fc` backup**, perform a
restore test into another PostgreSQL database, and schedule a maintenance
window. Then, on a correctly configured operator environment:

```bash
python scripts/ensure_plans_unique.py
# The command above is READ ONLY and audits duplicates/nulls.

# ONLY AFTER backup and restore validation, in an approved maintenance window:
export AGROERP_PLANS_UNIQUE_MIGRATION=BACKUP_AND_RESTORE_VERIFIED_FOR_AGROERP_PLANS_2026_11_19
python scripts/ensure_plans_unique.py --apply
```

The tool defaults to audit mode, refuses missing backup confirmation on
`--apply`, checks duplicate and null rows before altering the table, and
re-checks under a write-excluding table lock. Run in a deliberate maintenance
window; schema changes can block ongoing writes. Do not store the dump or DB
credentials in GitHub.

## Not covered yet (do not call stage 1 full ERP security)

- Role-based authorization for multiple non-admin users, audit logging,
  ownership/creator controls, and granular permissions are later milestones.
- Purchasing needs and payer allocations still have known cross-season
  aggregation issues; stage 2 must isolate them before business deployment.
- Reports/PDF and parts of the purchasing system still use current reference
  field snapshots rather than historical FieldSeason; stage 2 must fix this.
- No change to existing production database/data or Render deployment.
- GitHub Actions tests use ephemeral SQLite; a restore-backed PostgreSQL
  integration test is still needed before merging into production.
