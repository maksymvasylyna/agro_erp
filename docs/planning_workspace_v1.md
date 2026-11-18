# AgroERP — Planning workspace V1 (pilot, 2026-11-18)

## Purpose
A reversible, non-destructive working prototype of a technology plan at the
level of a **seasonal crop allocation** (`FieldPlanting.id`). Existing legacy
`plans`, `treatments`, purchasing and payer allocation tables are untouched.

Production source archive before this work:
`archive/pre-planning-rebuild-2026-11-18`, from commit
`a74d1f42cd9a827ce63ef7a44203774486a1a102`.
Feature branch: `feature/planning-rebuild-v1-2026-11-18`.

**Important:** the source archive does NOT include the PostgreSQL database or
Render environment/credentials. Before any migration or production rollout,
export and verify an independent `pg_dump -Fc` and test a restore to a
separate database. Do not store a DB dump or secrets in this public GitHub repo.

## Scope
- Entry: Plans → **Технологічні плани — нова механіка (пілот)**.
- Only plantings from the currently selected global harvest season are shown.
- Cluster → company → crop → status filtering, automatically applied.
- Each crop allocation has an independent plan (one plan per planting).
- Each plan has ordered operations (treatment type, label, BBCH, date,
  application basis in hectares or tonnes, basis quantity).
- Each operation contains one or more product lines (product, rate,
  quantity computed on the server and saved as a fixed snapshot).
- Statuses: draft → ready → approved; ready plans can be revised, and approved
  plans can be unlocked only by an administrator. Approved plans cannot be edited.
- Closed seasons prevent edits and status transitions; posted season ID must
  match the currently selected season.

## Architectural limits / do not present as production-ready
- New tables `technology_plans`, `technology_operations`,
  `technology_operation_products` are additive and separate from legacy plans.
- **Pilot plans do not yet drive purchase needs, warehouse or payers**.
  Existing purchase allocation logic is season-unsafe and relies on legacy
  field snapshots. Do not combine or migrate these automatically.
- No import of old plans, no data deletion, no changes to production
  `main`, no Render deployment of this branch.
- Access control is temporary: approval/unlock check existing admin session;
  creating and editing drafts still await full role-based permissions.
- Filter UI is single-select in this pilot; dynamic multi-select and exports
  remain later milestones.
- Tests run on ephemeral SQLite and are not a substitute for Postgres staging.

## Preconditions before merge or preview deployment
1. Obtain and verify an independent full database snapshot.
2. Run CI and a restore-backed staging smoke test.
3. Audit migrations and indexes on a copy of the schema.
4. Validate multi-crop plans and product quantities with agronomy users.
5. Agree on migrations/integration to canonical purchases and payer allocations.
6. Add audit history, server validation of product applicability, product price
   and package rounding in a later stage.
